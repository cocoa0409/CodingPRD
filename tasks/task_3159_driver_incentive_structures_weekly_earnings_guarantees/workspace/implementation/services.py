"""Business logic: shared helpers, calculations, state-transition cascades.

All money is integer cents. Zone/forecast/streak multipliers use floor;
shortfall recommendation uses ceil. The per-ride-then-sum rounding order of
PRD §2.6 is pinned.
"""
import math
import uuid
from datetime import datetime, timezone, timedelta

import db
from errors import (
    err_appeal_adjustment_required,
    err_appeal_identity_mismatch,
    err_appeal_not_escalatable,
    err_appeal_rounds_exhausted,
    err_budget_exceeded,
    err_cross_market_reference,
    err_driver_ineligible,
    err_enrollment_duplicate,
    err_forecast_not_draft,
    err_fraud_restricted,
    err_geo_cell_unknown,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_program_config_incomplete,
    err_program_not_guarantee,
    err_program_window_conflict,
    err_ride_already_terminal,
    err_ride_not_completable,
    err_settlement_already_paid,
    err_settlement_rides_pending,
    err_stale_market_version,
    err_stale_program_version,
    err_statement_settlements_open,
)

# ---------------------------------------------------------------------------
# Constants from the scaffold
# ---------------------------------------------------------------------------
WINDOW_SIZE = 100
ACCEPT_OK_BPS = 9000
ACCEPT_MIN_BPS = 7500
CANCEL_OK_BPS = 1000
CANCEL_MAX_BPS = 2000
MIN_OFFERS = 20

RESTRICT_MIN = 10
WATCH_MIN = 4
DECAY_BUCKET_WEEKS = 4

RIDE_TYPES = ("STANDARD", "SHARED", "SCHEDULED", "LUX")
PROGRAM_TYPES = ("STREAK", "BONUS_ZONE", "CHALLENGE", "GUARANTEE")
STACKING_CLASSES = ("STACKABLE", "EXCLUSIVE")
SIGNAL_TYPES = ("INFLATED_RIDE", "COLLUSION", "LOCATION_SPOOF")
SUBJECT_TYPES = ("ELIGIBILITY", "STATEMENT")
APPEAL_OUTCOMES = ("UPHELD", "OVERTURNED")
CANCELLED_BY = ("DRIVER", "RIDER")

RIDE_TERMINAL = ("COMPLETED", "DRIVER_CANCELLED", "RIDER_CANCELLED", "DECLINED", "VOIDED")

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def iso_now(dt=None):
    dt = dt or db.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field="timestamp"):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"{field} is malformed")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_entity(extra=None):
    now_iso = iso_now()
    ent = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    if extra:
        ent.update(extra)
    return ent


def touch(ent):
    ent["updated_at"] = iso_now()
    ent["version"] += 1


def require_int(value, field, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid_request(f"{field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid_request(f"{field} must be <= {maximum}")
    if exclusive_min is not None and value <= exclusive_min:
        raise err_invalid_request(f"{field} must be > {exclusive_min}")
    return value


def require_str(value, field, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and value == ""):
        raise err_invalid_request(f"{field} must be a non-empty string")
    return value


def require_enum(value, field, choices):
    if value not in choices:
        raise err_invalid_request(f"{field} must be one of {choices}")
    return value


def require_list_of_str(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise err_invalid_request(f"{field} must be a list of strings")
    return value


def json_body():
    from flask import request

    if not request.data:
        return {}
    try:
        body = request.get_json(force=True)
    except Exception:
        raise err_invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    return body


def get_pagination(args):
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    limit, offset = get_pagination(args)
    items_sorted = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items_sorted)
    page = items_sorted[offset : offset + limit]
    return page, limit, offset, total


# ---------------------------------------------------------------------------
# Existence helpers (left-to-right path validation)
# ---------------------------------------------------------------------------


def get_market_or_404(mid):
    m = db.markets.get(mid)
    if m is None:
        raise err_not_found("Market not found")
    return m


def get_driver_or_404(did):
    d = db.drivers.get(did)
    if d is None:
        raise err_not_found("Driver not found")
    return d


def get_program_or_404(pid):
    p = db.programs.get(pid)
    if p is None:
        raise err_not_found("IncentiveProgram not found")
    return p


def get_ride_or_404(rid):
    r = db.rides.get(rid)
    if r is None:
        raise err_not_found("Ride not found")
    return r


def get_enrollment_or_404(eid):
    e = db.enrollments.get(eid)
    if e is None:
        raise err_not_found("IncentiveEnrollment not found")
    return e


def get_settlement_or_404(sid):
    s = db.settlements.get(sid)
    if s is None:
        raise err_not_found("GuaranteeSettlement not found")
    return s


def get_statement_or_404(sid):
    s = db.statements.get(sid)
    if s is None:
        raise err_not_found("EarningsStatement not found")
    return s


def get_appeal_or_404(aid):
    a = db.appeals.get(aid)
    if a is None:
        raise err_not_found("Appeal not found")
    return a


def get_flag_or_404(fid):
    f = db.fraud_flags.get(fid)
    if f is None:
        raise err_not_found("FraudFlag not found")
    return f


def get_shortfall_or_404(sid):
    s = db.shortfalls.get(sid)
    if s is None:
        raise err_not_found("SupplyShortfall not found")
    return s


def get_forecast_or_404(fid):
    f = db.forecasts.get(fid)
    if f is None:
        raise err_not_found("CostForecast not found")
    return f


# ---------------------------------------------------------------------------
# Week bucketing
# ---------------------------------------------------------------------------


def week_start_of(dt):
    """Monday 00:00:00Z of the week containing dt."""
    monday = dt.date() - timedelta(days=dt.weekday())
    return datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Market budget derived fields (mutations bump version/updated_at per §2.4)
# ---------------------------------------------------------------------------


def market_recompute(m, touch_it=True):
    m["budget_reserved_cents"] = sum(
        p.get("promised_make_up_max_cents") or 0
        for p in db.programs.values()
        if p["market_id"] == m["id"] and p["status"] == "ACTIVE"
    )
    if touch_it:
        touch(m)


def market_available(m):
    return m["incentive_budget_cents"] - m["budget_spent_cents"] - m["budget_reserved_cents"]


def market_add_spend(m, cents):
    if cents <= 0:
        return
    m["budget_spent_cents"] += cents
    touch(m)


# ---------------------------------------------------------------------------
# Expiry (lazy, evaluated against the logical clock)
# ---------------------------------------------------------------------------


def expire_due():
    """Evaluate lazy EXPIRED transitions against the logical clock."""
    now = db.now()
    for prog in list(db.programs.values()):
        if prog["status"] in ("ACTIVE", "PAUSED"):
            try:
                wend = parse_iso(prog["window_end_utc"], "window_end_utc")
            except Exception:
                continue
            if now >= wend:
                # program expiry is implicit; enrollments expire explicitly
                pass
    for enr in list(db.enrollments.values()):
        if enr["status"] == "ACTIVE":
            prog = db.programs.get(enr["program_id"])
            if prog is None:
                continue
            try:
                wend = parse_iso(prog["window_end_utc"], "window_end_utc")
            except Exception:
                continue
            if now >= wend:
                enr["status"] = "EXPIRED"
                touch(enr)
    for sf in list(db.shortfalls.values()):
        if sf["status"] == "OPEN":
            m = db.markets.get(sf["market_id"])
            if m is None:
                continue
            anchor = week_start_of(parse_iso(m["created_at"]))
            expires_at = anchor + timedelta(weeks=1, hours=sf["hour_bucket"])
            if now > expires_at:
                sf["status"] = "EXPIRED"
                touch(sf)


def touch_expiry(entity_kind, entity):
    """Evaluate expiry for a single entity about to be read/written."""
    now = db.now()
    if entity_kind == "enrollment" and entity["status"] == "ACTIVE":
        prog = db.programs.get(entity["program_id"])
        if prog is not None:
            wend = parse_iso(prog["window_end_utc"], "window_end_utc")
            if now >= wend:
                entity["status"] = "EXPIRED"
                touch(entity)
    elif entity_kind == "shortfall" and entity["status"] == "OPEN":
        m = db.markets.get(entity["market_id"])
        if m is not None:
            anchor = week_start_of(parse_iso(m["created_at"]))
            expires_at = anchor + timedelta(weeks=1, hours=entity["hour_bucket"])
            if now > expires_at:
                entity["status"] = "EXPIRED"
                touch(entity)


# ---------------------------------------------------------------------------
# Rolling rates (calculations.rolling_rates, rate_posture_derivation)
# ---------------------------------------------------------------------------


def _rate_window(driver_id):
    return db.rate_events.get(driver_id, [])


def rolling_recompute(driver, mutate=True):
    events = _rate_window(driver["id"])[-WINDOW_SIZE:]
    offers = sum(1 for e in events if e["type"] in ("OFFER_ACCEPTED", "OFFER_DECLINED"))
    accepted = sum(1 for e in events if e["type"] == "OFFER_ACCEPTED")
    cancelled = sum(1 for e in events if e["type"] == "DRIVER_CANCEL")
    acc = 10000 if offers == 0 else (10000 * accepted) // offers
    canc = 0 if accepted == 0 else (10000 * cancelled) // accepted

    old_posture = driver["rate_posture"]
    if offers < MIN_OFFERS:
        new_posture = old_posture  # insufficient data: unchanged
    elif acc >= ACCEPT_OK_BPS and canc <= CANCEL_OK_BPS:
        new_posture = "ELIGIBLE"
    elif acc >= ACCEPT_MIN_BPS and canc <= CANCEL_MAX_BPS:
        new_posture = "PROBATION"
    else:
        new_posture = "INELIGIBLE"

    if mutate:
        driver["offers_total"] = offers
        driver["accepted_total"] = accepted
        driver["cancelled_total"] = cancelled
        driver["acceptance_rate_bps"] = acc
        driver["cancellation_rate_bps"] = canc
        driver["rate_posture"] = new_posture
        touch(driver)

    return old_posture, new_posture


def record_rate_event(driver, event_type, recorded_at=None):
    events = db.rate_events.setdefault(driver["id"], [])
    events.append(
        {
            "type": event_type,
            "recorded_at": iso_now(recorded_at or db.now()),
            "created_at": iso_now(),
        }
    )
    # keep bounded to window
    if len(events) > WINDOW_SIZE * 4:
        del events[: len(events) - WINDOW_SIZE]


def maybe_rate_posture_cascade(driver, old_posture, new_posture):
    if new_posture == "INELIGIBLE" and old_posture != "INELIGIBLE":
        for enr in list(db.enrollments.values()):
            if enr["driver_id"] == driver["id"] and enr["status"] == "ACTIVE":
                cancel_enrollment(enr)


# ---------------------------------------------------------------------------
# Enrollment cancel cascade (releases zone capacity implicitly)
# ---------------------------------------------------------------------------


def cancel_enrollment(enr):
    if enr["status"] != "ACTIVE":
        return
    enr["status"] = "CANCELLED"
    touch(enr)


# ---------------------------------------------------------------------------
# Fraud posture (calculations.fraud_score, fraud_posture_derivation)
# ---------------------------------------------------------------------------


def _fraud_scores(driver):
    confirmed = [
        f for f in db.fraud_flags.values() if f["driver_id"] == driver["id"] and f["status"] == "CONFIRMED"
    ]
    acute = sum(f["severity"] for f in confirmed)
    chronic = 0
    now = db.now()
    for f in confirmed:
        conf_at_str = f.get("confirmed_at")
        if conf_at_str:
            conf_at = parse_iso(conf_at_str)
        else:
            conf_at = parse_iso(f["updated_at"])
        age_seconds = max(0, (now - conf_at).total_seconds())
        bucket_seconds = DECAY_BUCKET_WEEKS * 7 * 24 * 3600
        age_bucket = int(age_seconds // bucket_seconds)
        chronic += (f["severity"] * 100) // (2 ** age_bucket) // 100
    return acute, chronic


def fraud_posture_recompute(driver):
    acute, chronic = _fraud_scores(driver)
    driver["acute_score"] = acute
    driver["chronic_score"] = chronic
    old = driver["fraud_posture"]
    if acute >= RESTRICT_MIN:
        new = "RESTRICTED"
    elif acute >= WATCH_MIN or chronic >= WATCH_MIN:
        new = "WATCH"
    else:
        new = "CLEAR"
    driver["fraud_posture"] = new
    touch(driver)
    return old, new


def maybe_fraud_posture_cascade(driver, old, new):
    if new == "RESTRICTED" and old != "RESTRICTED":
        for enr in list(db.enrollments.values()):
            if enr["driver_id"] == driver["id"] and enr["status"] == "ACTIVE":
                cancel_enrollment(enr)


# ---------------------------------------------------------------------------
# Ride helpers
# ---------------------------------------------------------------------------


def ride_week(ride):
    comp = ride.get("completed_at")
    if comp:
        return week_start_of(parse_iso(comp))
    return None


def ride_completed_in_week(ride, week_start):
    return ride_week(ride) == week_start


def fold_offer_event(driver):
    """OFFERED recorded; offer folds into rolling rates immediately."""
    record_rate_event(driver, "OFFER_RECORDED")


def fold_accept_event(driver):
    record_rate_event(driver, "OFFER_ACCEPTED")
    old, new = rolling_recompute(driver)
    maybe_rate_posture_cascade(driver, old, new)


def fold_decline_event(driver):
    record_rate_event(driver, "OFFER_DECLINED")
    old, new = rolling_recompute(driver)
    maybe_rate_posture_cascade(driver, old, new)


def fold_driver_cancel_event(driver):
    record_rate_event(driver, "DRIVER_CANCEL")
    old, new = rolling_recompute(driver)
    maybe_rate_posture_cascade(driver, old, new)


def break_streaks(driver):
    for enr in db.enrollments.values():
        if enr["driver_id"] != driver["id"] or enr["status"] != "ACTIVE":
            continue
        prog = db.programs.get(enr["program_id"])
        if prog and prog["program_type"] == "STREAK":
            enr["streak_broken"] = True
            enr["progress_count"] = 0
            touch(enr)


# ---------------------------------------------------------------------------
# Completion: qualifying earnings + enrollment progress + payouts (§3.6/§3.7)
# ---------------------------------------------------------------------------


def _program_covers_now(prog):
    now = db.now()
    ws = parse_iso(prog["window_start_utc"])
    we = parse_iso(prog["window_end_utc"])
    return ws <= now < we


def process_ride_completion(ride, driver):
    ride["qualifying_earnings_cents"] = ride["base_fare_cents"]
    ride["completed_at"] = iso_now()
    ride["status"] = "COMPLETED"
    touch(ride)

    now = db.now()
    driver_enrollments = [
        e for e in db.enrollments.values() if e["driver_id"] == driver["id"] and e["status"] == "ACTIVE"
    ]

    advanced = []  # (enrollment, program)
    for enr in driver_enrollments:
        prog = db.programs.get(enr["program_id"])
        if prog is None or prog["status"] != "ACTIVE":
            continue
        if not _program_covers_now(prog):
            continue
        if ride["ride_type"] in (prog.get("excluded_ride_types") or []):
            continue
        ptype = prog["program_type"]
        if ptype == "BONUS_ZONE":
            if ride["geo_cell_id"] != prog.get("geo_cell_id"):
                continue
        # STREAK/CHALLENGE/GUARANTEE qualify across market cells
        advanced.append((enr, prog))

    exclusive_advanced = any(p["stacking_class"] == "EXCLUSIVE" for _, p in advanced)

    # find an ACTIVE BONUS_ZONE enrollment of this driver covering ride cell (for streak boost)
    zone_boost_bps = None
    for enr, prog in advanced:
        if prog["program_type"] == "BONUS_ZONE" and ride["geo_cell_id"] == prog.get("geo_cell_id"):
            zone_boost_bps = prog["zone_multiplier_bps"]
            break

    market = db.markets.get(ride["market_id"])
    ride_advanced_exclusive = exclusive_advanced

    for enr, prog in advanced:
        ptype = prog["program_type"]
        if ptype == "STREAK":
            if enr.get("streak_broken"):
                continue
            enr["progress_count"] += 1
            touch(enr)
            if enr["progress_count"] >= prog["streak_length"]:
                base = prog["streak_payout_cents"]
                boost = 0
                if zone_boost_bps is not None:
                    boost = (base * (zone_boost_bps - 10000)) // 10000
                raw = base + boost
                if prog["stacking_class"] == "STACKABLE" and ride_advanced_exclusive:
                    payout = 0
                else:
                    avail = market_available(market) if market else raw
                    payout = min(raw, avail)
                enr["payout_cents"] = payout
                enr["status"] = "COMPLETED"
                enr["completed_at"] = iso_now()
                touch(enr)
                if market is not None and payout > 0:
                    market_add_spend(market, payout)
        elif ptype == "CHALLENGE":
            enr["progress_count"] += 1
            touch(enr)
            if enr["progress_count"] >= prog["challenge_ride_target"]:
                if prog["stacking_class"] == "STACKABLE" and ride_advanced_exclusive:
                    payout = 0
                else:
                    payout = prog["challenge_payout_cents"]
                enr["payout_cents"] = payout
                enr["status"] = "COMPLETED"
                enr["completed_at"] = iso_now()
                touch(enr)
                if market is not None and payout > 0:
                    market_add_spend(market, payout)
        elif ptype == "BONUS_ZONE":
            per_ride = (ride["base_fare_cents"] * (prog["zone_multiplier_bps"] - 10000)) // 10000
            enr["payout_cents"] = (enr.get("payout_cents") or 0) + per_ride
            touch(enr)
            if market is not None and per_ride > 0:
                market_add_spend(market, per_ride)
        elif ptype == "GUARANTEE":
            enr["progress_count"] += 1
            enr["earned_qualifying_cents"] = (enr.get("earned_qualifying_cents") or 0) + ride[
                "qualifying_earnings_cents"
            ]
            touch(enr)


# ---------------------------------------------------------------------------
# Guarantee settlement computations
# ---------------------------------------------------------------------------


def settlement_compute_fields(driver, program, week_start, variant):
    rides = [
        r
        for r in db.rides.values()
        if r["driver_id"] == driver["id"] and r["status"] == "COMPLETED"
    ]
    in_week = [r for r in rides if ride_completed_in_week(r, week_start)]
    if variant == "PROVISIONAL":
        in_week = [r for r in in_week if r["status"] != "UNDER_REVIEW"]
    # Rides whose ride_type is in the program's excluded_ride_types are
    # non-excluded-filtered out of the guarantee basis per PRD §3.6.
    excluded = set(program.get("excluded_ride_types") or [])
    if excluded:
        in_week = [r for r in in_week if r["ride_type"] not in excluded]
    # VOIDED rides are excluded by the COMPLETED status filter
    count = len(in_week)
    actual = sum(r["qualifying_earnings_cents"] for r in in_week)
    promised = program["guaranteed_weekly_cents"]
    if count < program["guaranteed_min_rides"]:
        make_up = 0
    else:
        make_up = max(0, promised - actual)
    return promised, actual, count, make_up


# ---------------------------------------------------------------------------
# Statement computations
# ---------------------------------------------------------------------------


def statement_compute_fields(driver, week_start):
    base = tips = 0
    for r in db.rides.values():
        if r["driver_id"] != driver["id"] or r["status"] != "COMPLETED":
            continue
        if ride_completed_in_week(r, week_start):
            base += r["base_fare_cents"]
            tips += r["tips_cents"]
    bonus = 0
    for e in db.enrollments.values():
        if e["driver_id"] != driver["id"] or e["status"] != "COMPLETED":
            continue
        comp = e.get("completed_at")
        if comp and week_start_of(parse_iso(comp)) == week_start:
            bonus += e.get("payout_cents") or 0
    make_up = 0
    for s in db.settlements.values():
        if s["driver_id"] != driver["id"] or s["status"] != "PAID":
            continue
        if parse_iso(s["week_start_utc"]) == week_start:
            make_up += s["make_up_cents"]
    adjustments = 0
    existing = next(
        (
            s
            for s in db.statements.values()
            if s["driver_id"] == driver["id"] and parse_iso(s["week_start_utc"]) == week_start
        ),
        None,
    )
    if existing is not None:
        adjustments = existing.get("adjustments_cents", 0)
    total = base + tips + bonus + make_up + adjustments
    return base, tips, bonus, make_up, adjustments, total


def statement_recompute_for_week(driver_id, week_start):
    for s in db.statements.values():
        if s["driver_id"] == driver_id and parse_iso(s["week_start_utc"]) == week_start:
            base, tips, bonus, make_up, adjustments, total = statement_compute_fields(
                db.drivers[driver_id], week_start
            )
            s["base_fares_cents"] = base
            s["tips_cents_total"] = tips
            s["bonus_total_cents"] = bonus
            s["make_up_total_cents"] = make_up
            s["adjustments_cents"] = adjustments
            s["total_cents"] = total
            touch(s)


# ---------------------------------------------------------------------------
# Serializers (public views)
# ---------------------------------------------------------------------------


def market_view(m):
    return {
        "id": m["id"],
        "market_code": m["market_code"],
        "geo_cells": list(m["geo_cells"]),
        "incentive_budget_cents": m["incentive_budget_cents"],
        "budget_spent_cents": m["budget_spent_cents"],
        "budget_reserved_cents": m["budget_reserved_cents"],
        "budget_available_cents": m["incentive_budget_cents"]
        - m["budget_spent_cents"]
        - m["budget_reserved_cents"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def driver_view(d):
    return {
        "id": d["id"],
        "market_id": d["market_id"],
        "display_name": d["display_name"],
        "rate_posture": d["rate_posture"],
        "fraud_posture": d["fraud_posture"],
        "acceptance_rate_bps": d["acceptance_rate_bps"],
        "cancellation_rate_bps": d["cancellation_rate_bps"],
        "offers_total": d["offers_total"],
        "accepted_total": d["accepted_total"],
        "cancelled_total": d["cancelled_total"],
        "account_status": d["account_status"],
        "acute_score": d.get("acute_score", 0),
        "chronic_score": d.get("chronic_score", 0),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def program_view(p):
    return {
        "id": p["id"],
        "market_id": p["market_id"],
        "program_type": p["program_type"],
        "title": p["title"],
        "window_start_utc": p["window_start_utc"],
        "window_end_utc": p["window_end_utc"],
        "geo_cell_id": p.get("geo_cell_id"),
        "stacking_class": p["stacking_class"],
        "excluded_ride_types": list(p.get("excluded_ride_types") or []),
        "streak_length": p.get("streak_length"),
        "streak_payout_cents": p.get("streak_payout_cents"),
        "zone_multiplier_bps": p.get("zone_multiplier_bps"),
        "challenge_ride_target": p.get("challenge_ride_target"),
        "challenge_payout_cents": p.get("challenge_payout_cents"),
        "guaranteed_weekly_cents": p.get("guaranteed_weekly_cents"),
        "guaranteed_min_rides": p.get("guaranteed_min_rides"),
        "promised_make_up_max_cents": p.get("promised_make_up_max_cents", 0),
        "capacity": p.get("capacity"),
        "status": p["status"],
        "forecast_headroom_cents": p.get("forecast_headroom_cents"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ride_view(r):
    return {
        "id": r["id"],
        "driver_id": r["driver_id"],
        "market_id": r["market_id"],
        "ride_type": r["ride_type"],
        "geo_cell_id": r["geo_cell_id"],
        "base_fare_cents": r["base_fare_cents"],
        "tips_cents": r["tips_cents"],
        "request_offer_recorded": r["request_offer_recorded"],
        "status": r["status"],
        "qualifying_earnings_cents": r["qualifying_earnings_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def enrollment_view(e):
    return {
        "id": e["id"],
        "driver_id": e["driver_id"],
        "program_id": e["program_id"],
        "status": e["status"],
        "progress_count": e["progress_count"],
        "streak_broken": e["streak_broken"],
        "payout_cents": e["payout_cents"],
        "earned_qualifying_cents": e.get("earned_qualifying_cents", 0),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def settlement_view(s):
    return {
        "id": s["id"],
        "driver_id": s["driver_id"],
        "program_id": s["program_id"],
        "week_start_utc": s["week_start_utc"],
        "promised_cents": s["promised_cents"],
        "actual_gross_cents": s["actual_gross_cents"],
        "qualifying_ride_count": s["qualifying_ride_count"],
        "make_up_cents": s["make_up_cents"],
        "basis_variant": s["basis_variant"],
        "status": s["status"],
        "paid_at_utc": s.get("paid_at_utc"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def statement_view(s):
    return {
        "id": s["id"],
        "driver_id": s["driver_id"],
        "week_start_utc": s["week_start_utc"],
        "base_fares_cents": s["base_fares_cents"],
        "tips_cents_total": s["tips_cents_total"],
        "bonus_total_cents": s["bonus_total_cents"],
        "make_up_total_cents": s["make_up_total_cents"],
        "adjustments_cents": s["adjustments_cents"],
        "total_cents": s["total_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def appeal_view(a):
    return {
        "id": a["id"],
        "driver_id": a["driver_id"],
        "subject_type": a["subject_type"],
        "statement_id": a.get("statement_id"),
        "reason": a["reason"],
        "round_count": a["round_count"],
        "status": a["status"],
        "adjustment_cents": a.get("adjustment_cents"),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def fraud_flag_view(f):
    return {
        "id": f["id"],
        "driver_id": f["driver_id"],
        "ride_id": f["ride_id"],
        "ring_id": f.get("ring_id"),
        "signal_type": f["signal_type"],
        "acute_score": f.get("acute_score", 0),
        "chronic_score": f.get("chronic_score", 0),
        "severity": f["severity"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def shortfall_view(s):
    return {
        "id": s["id"],
        "market_id": s["market_id"],
        "geo_cell_id": s["geo_cell_id"],
        "hour_bucket": s["hour_bucket"],
        "severity_bps": s["severity_bps"],
        "recommended_bonus_cents": s["recommended_bonus_cents"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def forecast_view(f):
    return {
        "id": f["id"],
        "program_id": f["program_id"],
        "baseline_rides": f["baseline_rides"],
        "lift_bps": f["lift_bps"],
        "cannibalization_bps": f["cannibalization_bps"],
        "projected_incremental_rides": f["projected_incremental_rides"],
        "projected_cannibalized_rides": f["projected_cannibalized_rides"],
        "projected_cost_cents": f["projected_cost_cents"],
        "forecast_revision": f["forecast_revision"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }
