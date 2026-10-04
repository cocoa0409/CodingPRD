"""IncentiveProgram endpoints."""
from flask import Blueprint, request

import db
from errors import (
    err_budget_exceeded,
    err_geo_cell_unknown,
    err_invalid_request,
    err_invalid_state,
    err_program_config_incomplete,
    err_program_window_conflict,
)
from middleware import require_roles
from response import success_list, success_object
from services import (
    get_market_or_404,
    get_program_or_404,
    market_available,
    market_recompute,
    new_entity,
    paginate,
    parse_iso,
    program_view,
    require_enum,
    require_int,
    require_list_of_str,
    require_str,
    touch,
    PROGRAM_TYPES,
    RIDE_TYPES,
    STACKING_CLASSES,
)

bp = Blueprint("programs", __name__)

ALL_READ = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst", "Driver")


def _validate_program_config(body):
    """Priority 9 (config completeness) and type-specific rules."""
    ptype = body.get("program_type")
    if ptype == "STREAK":
        if body.get("streak_length") is None or body.get("streak_payout_cents") is None:
            raise err_program_config_incomplete("STREAK requires streak_length and streak_payout_cents")
        require_int(body["streak_length"], "streak_length", minimum=1)
        require_int(body["streak_payout_cents"], "streak_payout_cents", minimum=0)
    elif ptype == "BONUS_ZONE":
        if body.get("geo_cell_id") is None:
            raise err_program_config_incomplete("BONUS_ZONE requires geo_cell_id")
        if body.get("zone_multiplier_bps") is None:
            raise err_program_config_incomplete("BONUS_ZONE requires zone_multiplier_bps")
        require_int(body["zone_multiplier_bps"], "zone_multiplier_bps", exclusive_min=10000)
        if body.get("capacity") is not None:
            require_int(body["capacity"], "capacity", minimum=1)
    elif ptype == "CHALLENGE":
        if body.get("challenge_ride_target") is None or body.get("challenge_payout_cents") is None:
            raise err_program_config_incomplete(
                "CHALLENGE requires challenge_ride_target and challenge_payout_cents"
            )
        require_int(body["challenge_ride_target"], "challenge_ride_target", minimum=1)
        require_int(body["challenge_payout_cents"], "challenge_payout_cents", minimum=0)
    elif ptype == "GUARANTEE":
        if body.get("guaranteed_weekly_cents") is None or body.get("guaranteed_min_rides") is None:
            raise err_program_config_incomplete(
                "GUARANTEE requires guaranteed_weekly_cents and guaranteed_min_rides"
            )
        require_int(body["guaranteed_weekly_cents"], "guaranteed_weekly_cents", minimum=0)
        require_int(body["guaranteed_min_rides"], "guaranteed_min_rides", minimum=0)


@bp.post("/incentive-programs")
@require_roles("IncentiveOps")
def create_program(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")

    # existence (market first)
    market_id = body.get("market_id")
    if not isinstance(market_id, str):
        raise err_invalid_request("market_id is required")
    market = get_market_or_404(market_id)

    # shape basics
    ptype = require_enum(body.get("program_type"), "program_type", PROGRAM_TYPES)
    title = require_str(body.get("title"), "title")
    stacking = require_enum(body.get("stacking_class"), "stacking_class", STACKING_CLASSES)
    excluded = body.get("excluded_ride_types")
    if excluded is None:
        excluded = []
    excluded = require_list_of_str(excluded, "excluded_ride_types")
    for rt in excluded:
        require_enum(rt, "excluded_ride_types", RIDE_TYPES)

    # window well-formedness (temporal)
    ws_raw = body.get("window_start_utc")
    we_raw = body.get("window_end_utc")
    if ws_raw is None or we_raw is None:
        raise err_program_window_conflict("window_start_utc and window_end_utc are required")
    ws = parse_iso(ws_raw, "window_start_utc")
    we = parse_iso(we_raw, "window_end_utc")
    if not (ws < we):
        raise err_program_window_conflict("window_start_utc must be < window_end_utc")

    # config completeness
    _validate_program_config(body)

    geo_cell_id = body.get("geo_cell_id")
    if ptype == "BONUS_ZONE":
        if geo_cell_id not in market["geo_cells"]:
            raise err_geo_cell_unknown()
    else:
        geo_cell_id = None

    p = new_entity(
        {
            "market_id": market_id,
            "program_type": ptype,
            "title": title,
            "window_start_utc": iso_format(ws),
            "window_end_utc": iso_format(we),
            "geo_cell_id": geo_cell_id,
            "stacking_class": stacking,
            "excluded_ride_types": list(excluded),
            "streak_length": body.get("streak_length"),
            "streak_payout_cents": body.get("streak_payout_cents"),
            "zone_multiplier_bps": body.get("zone_multiplier_bps"),
            "challenge_ride_target": body.get("challenge_ride_target"),
            "challenge_payout_cents": body.get("challenge_payout_cents"),
            "guaranteed_weekly_cents": body.get("guaranteed_weekly_cents"),
            "guaranteed_min_rides": body.get("guaranteed_min_rides"),
            "promised_make_up_max_cents": 0,
            "capacity": body.get("capacity"),
            "status": "DRAFT",
            "forecast_headroom_cents": None,
        }
    )
    db.programs[p["id"]] = p
    return success_object(program_view(p), 201)


def iso_format(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.get("/incentive-programs/<pid>")
@require_roles(*ALL_READ)
def get_program(pid, _user_id, _role):
    p = get_program_or_404(pid)
    return success_object(program_view(p))


@bp.get("/incentive-programs")
@require_roles(*ALL_READ)
def list_programs(_user_id, _role):
    items = list(db.programs.values())
    market_id = request.args.get("market_id")
    ptype = request.args.get("program_type")
    status = request.args.get("status")
    if market_id is not None:
        items = [p for p in items if p["market_id"] == market_id]
    if ptype is not None:
        items = [p for p in items if p["program_type"] == ptype]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([program_view(p) for p in page], limit, offset, total)


def _windows_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def _check_zone_overlap(market_id, geo_cell_id, ws, we, exclude_id=None):
    for other in db.programs.values():
        if other["id"] == exclude_id:
            continue
        if other["market_id"] != market_id:
            continue
        if other["program_type"] != "BONUS_ZONE":
            continue
        if other["status"] != "ACTIVE":
            continue
        if other.get("geo_cell_id") != geo_cell_id:
            continue
        ows = parse_iso(other["window_start_utc"])
        owe = parse_iso(other["window_end_utc"])
        if _windows_overlap(ws, we, ows, owe):
            raise err_program_window_conflict(
                "Another ACTIVE BONUS_ZONE covers this geo cell with an overlapping window"
            )


def _latest_forecast(program_id):
    cands = [f for f in db.forecasts.values() if f["program_id"] == program_id]
    if not cands:
        return None
    return max(cands, key=lambda f: f["forecast_revision"])


@bp.post("/incentive-programs/<pid>/activate")
@require_roles("IncentiveOps")
def activate_program(pid, _user_id, _role):
    p = get_program_or_404(pid)
    if p["status"] != "DRAFT":
        raise err_invalid_state("Program must be DRAFT to activate")
    market = get_market_or_404(p["market_id"])
    if market["status"] != "ACTIVE":
        raise err_invalid_state("Market must be ACTIVE")

    ws = parse_iso(p["window_start_utc"])
    we = parse_iso(p["window_end_utc"])
    if p["program_type"] == "BONUS_ZONE":
        _check_zone_overlap(market["id"], p["geo_cell_id"], ws, we, exclude_id=p["id"])

    # GUARANTEE budget reservation check
    if p["program_type"] == "GUARANTEE":
        if market_available(market) < p["guaranteed_weekly_cents"]:
            raise err_budget_exceeded("Guarantee reservation exceeds available budget")

    # forecast gating
    latest = _latest_forecast(p["id"])
    if latest is not None:
        if latest["status"] != "APPROVED":
            raise err_invalid_state("Latest CostForecast is not APPROVED")
        if latest["projected_cost_cents"] > market_available(market):
            raise err_budget_exceeded("Approved forecast cost exceeds available budget")

    p["status"] = "ACTIVE"
    if p["program_type"] == "GUARANTEE":
        p["promised_make_up_max_cents"] = p["guaranteed_weekly_cents"]
    touch(p)
    market_recompute(market, touch_it=True)
    return success_object(program_view(p))


@bp.post("/incentive-programs/<pid>/pause")
@require_roles("IncentiveOps")
def pause_program(pid, _user_id, _role):
    p = get_program_or_404(pid)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("Program must be ACTIVE to pause")
    market = get_market_or_404(p["market_id"])
    p["status"] = "PAUSED"
    if p["program_type"] == "GUARANTEE":
        p["promised_make_up_max_cents"] = 0
    touch(p)
    market_recompute(market, touch_it=True)
    return success_object(program_view(p))


@bp.post("/incentive-programs/<pid>/resume")
@require_roles("IncentiveOps")
def resume_program(pid, _user_id, _role):
    p = get_program_or_404(pid)
    if p["status"] != "PAUSED":
        raise err_invalid_state("Program must be PAUSED to resume")
    market = get_market_or_404(p["market_id"])
    if market["status"] != "ACTIVE":
        raise err_invalid_state("Market must be ACTIVE")
    if p["program_type"] == "GUARANTEE":
        if market_available(market) < p["guaranteed_weekly_cents"]:
            raise err_budget_exceeded("Guarantee reservation exceeds available budget")
    ws = parse_iso(p["window_start_utc"])
    we = parse_iso(p["window_end_utc"])
    if p["program_type"] == "BONUS_ZONE":
        _check_zone_overlap(market["id"], p["geo_cell_id"], ws, we, exclude_id=p["id"])
    p["status"] = "ACTIVE"
    if p["program_type"] == "GUARANTEE":
        p["promised_make_up_max_cents"] = p["guaranteed_weekly_cents"]
    touch(p)
    market_recompute(market, touch_it=True)
    return success_object(program_view(p))


@bp.post("/incentive-programs/<pid>/retire")
@require_roles("IncentiveOps")
def retire_program(pid, _user_id, _role):
    p = get_program_or_404(pid)
    if p["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise err_invalid_state("Program cannot be retired from its current state")
    for enr in db.enrollments.values():
        if enr["program_id"] == p["id"] and enr["status"] == "ACTIVE":
            raise err_invalid_state("Program has ACTIVE enrollments")
    market = get_market_or_404(p["market_id"])
    was_active_guarantee = p["status"] == "ACTIVE" and p["program_type"] == "GUARANTEE"
    p["status"] = "RETIRED"
    if p["program_type"] == "GUARANTEE":
        p["promised_make_up_max_cents"] = 0
    touch(p)
    if was_active_guarantee or p["program_type"] == "GUARANTEE":
        market_recompute(market, touch_it=True)
    # linked shortfalls -> ADDRESSED
    if p.get("geo_cell_id") is not None:
        ws = parse_iso(p["window_start_utc"])
        we = parse_iso(p["window_end_utc"])
        covered = _covered_hour_buckets(ws, we)
        for sf in db.shortfalls.values():
            if (
                sf["market_id"] == market["id"]
                and sf["status"] == "OPEN"
                and sf["geo_cell_id"] == p["geo_cell_id"]
                and sf["hour_bucket"] in covered
            ):
                sf["status"] = "ADDRESSED"
                touch(sf)
    return success_object(program_view(p))


def _covered_hour_buckets(ws, we):
    """Hours-of-week (0..167) covered by [ws, we)."""
    from datetime import datetime, timezone, timedelta

    # find the Monday 00:00Z of ws's week
    day = ws.date()
    monday = day - timedelta(days=day.weekday())
    anchor = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    covered = set()
    t = ws
    # walk hour by hour (bounded); windows are typically days at most
    steps = 0
    while t < we and steps < 24 * 366:
        hour = int((t - anchor).total_seconds() // 3600)
        if 0 <= hour <= 167:
            covered.add(hour)
        t = t + timedelta(hours=1)
        steps += 1
    return covered


@bp.get("/incentive-programs/<pid>/enrollments")
@require_roles("PlatformAdmin", "IncentiveOps", "PaymentsOfficer")
def list_program_enrollments(pid, _user_id, _role):
    p = get_program_or_404(pid)
    from services import enrollment_view, touch_expiry

    status = request.args.get("status")
    items = [e for e in db.enrollments.values() if e["program_id"] == p["id"]]
    for e in items:
        touch_expiry("enrollment", e)
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([enrollment_view(e) for e in page], limit, offset, total)


@bp.get("/incentive-programs/<pid>/cost-forecasts")
@require_roles("PlatformAdmin", "IncentiveOps")
def list_program_forecasts(pid, _user_id, _role):
    p = get_program_or_404(pid)
    from services import forecast_view

    status = request.args.get("status")
    items = [f for f in db.forecasts.values() if f["program_id"] == p["id"]]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([forecast_view(f) for f in page], limit, offset, total)


@bp.post("/incentive-programs/<pid>/cost-forecasts")
@require_roles("IncentiveOps")
def create_forecast(pid, _user_id, _role):
    from services import forecast_view

    p = get_program_or_404(pid)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    baseline = require_int(body.get("baseline_rides"), "baseline_rides", minimum=0)
    lift = require_int(body.get("lift_bps"), "lift_bps", minimum=0)
    cann = require_int(body.get("cannibalization_bps"), "cannibalization_bps", minimum=0)

    incremental = (baseline * lift) // 10000
    cannibalized = (incremental * cann) // 10000
    net_new = incremental - cannibalized

    ptype = p["program_type"]
    if ptype == "STREAK":
        per = max(1, p["streak_length"])
        cost = (net_new // per) * p["streak_payout_cents"]
    elif ptype == "CHALLENGE":
        per = max(1, p["challenge_ride_target"])
        cost = (net_new // per) * p["challenge_payout_cents"]
    elif ptype == "BONUS_ZONE":
        from datetime import timedelta

        market = get_market_or_404(p["market_id"])
        cutoff = db.now() - timedelta(weeks=4)
        fares = []
        for r in db.rides.values():
            if r["market_id"] != market["id"] or r["status"] != "COMPLETED":
                continue
            comp = r.get("completed_at")
            if not comp:
                continue
            if parse_iso(comp) >= cutoff:
                fares.append(r["base_fare_cents"])
        if fares:
            fares.sort()
            n = len(fares)
            median = fares[n // 2] if n % 2 == 1 else (fares[n // 2 - 1] + fares[n // 2]) // 2
        else:
            median = 0
        per_ride = (median * (p["zone_multiplier_bps"] - 10000)) // 10000
        cost = per_ride * net_new
    elif ptype == "GUARANTEE":
        cost = p["guaranteed_weekly_cents"]
    else:
        cost = 0

    revision = 1 + max(
        [0] + [f["forecast_revision"] for f in db.forecasts.values() if f["program_id"] == p["id"]]
    )
    f = new_entity(
        {
            "program_id": p["id"],
            "baseline_rides": baseline,
            "lift_bps": lift,
            "cannibalization_bps": cann,
            "projected_incremental_rides": incremental,
            "projected_cannibalized_rides": cannibalized,
            "projected_cost_cents": cost,
            "forecast_revision": revision,
            "status": "DRAFT",
        }
    )
    db.forecasts[f["id"]] = f
    return success_object(forecast_view(f), 201)
