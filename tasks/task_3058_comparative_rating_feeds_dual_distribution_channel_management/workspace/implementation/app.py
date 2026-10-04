"""Comparative Rating Dual Channel API — Flask implementation.

Every behavior traces to a verbatim sentence in PRD.md / SCAFFOLD.yaml.
Storage is in-memory only (db.DB); the store starts empty on every boot.
The logical clock defaults to 2026-09-01T00:00:00Z until advanced via
POST /_clock/set_current_utc; the server never falls back to wall-clock time
for domain behavior.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

from db import DB, new_id, now, iso, touch
from errors import ApiError, raise_err
from response import success, error
from middleware import get_auth, require_role, check_ownership

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def rhu(value):
    """Round half-up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    """Round half-up to 4 decimal places (ratios)."""
    return float(Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    """Parse an ISO8601 datetime string; raise ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise_err("ERR_INVALID_REQUEST", f"Expected ISO8601 datetime string, got {type(value).__name__}")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", f"Unparseable datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def get_body(required=False):
    if not request.data:
        if required:
            raise_err("ERR_INVALID_REQUEST", "Request body is required")
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum)


def req_num(body, field):
    v = body.get(field)
    if not _is_num(v):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a number")
    return v


def opt_num(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_num(body, field)


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        raise_err("ERR_INVALID_REQUEST", f"Field '{field}' is required")
    return parse_dt(v)


def opt_dt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return parse_dt(body[field])


def get_or_404(collection, rid, label="resource"):
    ent = collection.get(rid)
    if ent is None:
        raise_err("ERR_NOT_FOUND", f"{label} {rid} not found")
    return ent


def paginate(items):
    """Apply limit/offset from query args; return (page, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit must be in [1, 100]")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


# ---------------------------------------------------------------------------
# Lazy-state evaluation (PRD §2.9)
# ---------------------------------------------------------------------------

def quote_status(quote):
    """Quote status with lazy EXPIRED evaluation (never mutates version)."""
    if quote["status"] in ("QUOTED", "REFERRED_TO_AGENT", "AGENT_QUOTED"):
        if quote["expires_at"] is not None and now() >= quote["expires_at"]:
            return "EXPIRED"
    return quote["status"]


def appointment_status(appt):
    if appt["status"] == "ACTIVE":
        if appt["effective_end"] is not None and appt["effective_end"] <= now():
            return "EXPIRED"
    return appt["status"]


def has_active_appointment(agent_id, state_code, lob):
    for a in DB.appointments.values():
        if (a["agent_id"] == agent_id
                and a["state_code"] == state_code
                and a["line_of_business"] == lob
                and appointment_status(a) == "ACTIVE"):
            return True
    return False


def agent_has_any_active_appointment(agent_id):
    for a in DB.appointments.values():
        if a["agent_id"] == agent_id and appointment_status(a) == "ACTIVE":
            return True
    return False


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_common(e):
    return {
        "id": e["id"],
        "created_at": iso(e["created_at"]),
        "updated_at": iso(e["updated_at"]),
        "version": e["version"],
    }


def ser_product(p):
    out = ser_common(p)
    out.update({
        "product_code": p["product_code"],
        "line_of_business": p["line_of_business"],
        "state_code": p["state_code"],
        "channel_availability": p["channel_availability"],
        "coverage_rates": p["coverage_rates"],
        "direct_discount_pct": p["direct_discount_pct"],
        "agent_load_pct": p["agent_load_pct"],
        "bundle_credit_pct": p["bundle_credit_pct"],
        "min_premium_cents": p["min_premium_cents"],
        "direct_channel_max_premium_cents": p["direct_channel_max_premium_cents"],
        "bundle_eligible": p["bundle_eligible"],
        "status": p["status"],
    })
    return out


def ser_rater(r):
    out = ser_common(r)
    out.update({
        "rater_code": r["rater_code"],
        "display_name": r["display_name"],
        "feed_format_version": r["feed_format_version"],
        "accepted_line_of_business": r["accepted_line_of_business"],
    })
    return out


def ser_publication(p):
    out = ser_common(p)
    out.update({
        "rater_id": p["rater_id"],
        "product_id": p["product_id"],
        "effective_start": iso(p["effective_start"]),
        "effective_end": iso(p["effective_end"]),
        "rate_table_payload": p["rate_table_payload"],
        "status": p["status"],
        "published_at": iso(p["published_at"]) if p["published_at"] else None,
    })
    return out


def ser_agent(a):
    out = ser_common(a)
    out.update({
        "agency_name": a["agency_name"],
        "principal_name": a["principal_name"],
        "resident_state_code": a["resident_state_code"],
        "status": a["status"],
        "terminated_reason": a["terminated_reason"],
    })
    return out


def ser_appointment(a):
    out = ser_common(a)
    out.update({
        "agent_id": a["agent_id"],
        "state_code": a["state_code"],
        "line_of_business": a["line_of_business"],
        "effective_start": iso(a["effective_start"]),
        "effective_end": iso(a["effective_end"]) if a["effective_end"] else None,
        "status": appointment_status(a),
        "terminated_reason": a["terminated_reason"],
    })
    return out


def ser_schedule(s):
    out = ser_common(s)
    out.update({
        "agent_id": s["agent_id"],
        "line_of_business": s["line_of_business"],
        "effective_start": iso(s["effective_start"]),
        "effective_end": iso(s["effective_end"]) if s["effective_end"] else None,
        "tiers": s["tiers"],
        "contingent_bonus_eligible": s["contingent_bonus_eligible"],
        "status": s["status"],
    })
    return out


def ser_consumer(c):
    out = ser_common(c)
    out.update({
        "email": c["email"],
        "full_name": c["full_name"],
        "date_of_birth": c["date_of_birth"],
        "home_state_code": c["home_state_code"],
    })
    return out


def ser_quote(q):
    out = ser_common(q)
    out.update({
        "consumer_id": q["consumer_id"],
        "product_id": q["product_id"],
        "agent_id": q["agent_id"],
        "channel": q["channel"],
        "coverages": q["coverages"],
        "bundled_home_intended": q["bundled_home_intended"],
        "telematics_opt_in": q["telematics_opt_in"],
        "status": quote_status(q),
        "quoted_premium_cents": q["quoted_premium_cents"],
        "quoted_at": iso(q["quoted_at"]) if q["quoted_at"] else None,
        "expires_at": iso(q["expires_at"]) if q["expires_at"] else None,
        "rate_stale": q["rate_stale"],
        "referral_snapshot": q["referral_snapshot"],
        "rate_feed_publication_id": q["rate_feed_publication_id"],
    })
    return out


def ser_policy(p):
    out = ser_common(p)
    out.update({
        "quote_id": p["quote_id"],
        "consumer_id": p["consumer_id"],
        "agent_id": p["agent_id"],
        "product_id": p["product_id"],
        "channel": p["channel"],
        "inception_at": iso(p["inception_at"]),
        "term_days": p["term_days"],
        "written_premium_cents": p["written_premium_cents"],
        "status": p["status"],
        "cancelled_at": iso(p["cancelled_at"]) if p["cancelled_at"] else None,
        "earned_premium_cents": p["earned_premium_cents"],
        "unearned_premium_cents": p["unearned_premium_cents"],
        "per_policy_commission_cents": p["per_policy_commission_cents"],
        "clawback_cents": p["clawback_cents"],
    })
    return out


def ser_claim(c):
    out = ser_common(c)
    out.update({
        "policy_id": c["policy_id"],
        "claim_type": c["claim_type"],
        "incurred_amount_cents": c["incurred_amount_cents"],
        "status": c["status"],
        "reported_at": iso(c["reported_at"]),
    })
    return out


def ser_enrollment(e):
    out = ser_common(e)
    out.update({
        "policy_id": e["policy_id"],
        "channel": e["channel"],
        "status": e["status"],
        "driving_score": e["driving_score"],
        "upfront_discount_cents": e["upfront_discount_cents"],
        "discount_pct_applied": e["discount_pct_applied"],
        "adjustment_cents": e["adjustment_cents"],
    })
    return out


def ser_statement(s):
    out = ser_common(s)
    out.update({
        "agent_id": s["agent_id"],
        "period_start": iso(s["period_start"]),
        "period_end": iso(s["period_end"]),
        "status": s["status"],
        "written_premium_cents": s["written_premium_cents"],
        "commission_cents": s["commission_cents"],
        "clawback_cents": s["clawback_cents"],
        "net_payable_cents": s["net_payable_cents"],
        "line_items": s["line_items"],
    })
    return out


def ser_pool(p):
    out = ser_common(p)
    out.update({
        "year": p["year"],
        "pool_total_cents": p["pool_total_cents"],
        "loss_ratio_threshold": p["loss_ratio_threshold"],
        "growth_threshold_pct": p["growth_threshold_pct"],
        "status": p["status"],
        "settled_at": iso(p["settled_at"]) if p["settled_at"] else None,
        "undistributed_cents": p["undistributed_cents"],
    })
    return out


def ser_payout(p):
    out = ser_common(p)
    out.update({
        "pool_id": p["pool_id"],
        "agent_id": p["agent_id"],
        "earned_premium_cents": p["earned_premium_cents"],
        "eligible": p["eligible"],
        "ineligibility_reason": p["ineligibility_reason"],
        "payout_cents": p["payout_cents"],
    })
    return out


def ser_review(r):
    out = ser_common(r)
    out.update({
        "agent_id": r["agent_id"],
        "reason": r["reason"],
        "opened_by_user_id": r["opened_by_user_id"],
        "status": r["status"],
        "trailing_loss_ratio": r["trailing_loss_ratio"],
        "earned_premium_trailing_cents": r["earned_premium_trailing_cents"],
        "findings": r["findings"],
        "action": r["action"],
        "actioned_by_user_id": r["actioned_by_user_id"],
    })
    return out


def ser_placement(p):
    out = ser_common(p)
    out.update({
        "policy_id": p["policy_id"],
        "agent_id": p["agent_id"],
        "unaffiliated_carrier_name": p["unaffiliated_carrier_name"],
        "home_premium_cents": p["home_premium_cents"],
        "total_commission_cents": p["total_commission_cents"],
        "status": p["status"],
        "transferred_to_agent_id": p["transferred_to_agent_id"],
        "earned_commission_cents": p["earned_commission_cents"],
        "transferred_commission_cents": p["transferred_commission_cents"],
    })
    return out


def new_entity():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

DIRECT_TELEMATICS_UPFRONT_PCT = Decimal("0.15")


def channel_quote_premium(product, channel, coverages, bundled_home_intended):
    """§1.3 channel_quote_premium — per-line round-half-up, then sum, then floor."""
    if channel == "DIRECT":
        factor = Decimal(1) - Decimal(str(product["direct_discount_pct"]))
    else:
        factor = Decimal(1) + Decimal(str(product["agent_load_pct"]))
        if bundled_home_intended:
            factor -= Decimal(str(product["bundle_credit_pct"]))
    total = 0
    for cov in coverages:
        code = cov.get("coverage_code")
        tier = cov.get("tier")
        rate = product["coverage_rates"].get(code, {}).get(tier)
        if rate is None:
            raise_err("ERR_INVALID_REQUEST", f"Coverage {code}/{tier} not in product rate table")
        line = rhu(Decimal(rate) * factor)
        total += line
    return max(total, product["min_premium_cents"])


def score_table(score):
    if score >= 90:
        return Decimal("0.20")
    if score >= 70:
        return Decimal("0.10")
    return Decimal("0.00")


def days_between(start, end):
    """Whole calendar days in half-open [start, end)."""
    if end <= start:
        return 0
    return (end.date() - start.date()).days


def earned_in_window(policy, window_start, window_end):
    """§1.3 earned_premium_proration trailing-window variant."""
    span_start = max(policy["inception_at"], window_start)
    cancel = policy["cancelled_at"] if policy["cancelled_at"] else window_end
    span_end = min(window_end, cancel)
    days = days_between(span_start, span_end)
    if days <= 0:
        return 0
    return rhu(Decimal(policy["written_premium_cents"]) * days / policy["term_days"])


def trailing_earned_and_incurred(agent_id, as_of, window_days=365):
    """§1.3 trailing_loss_ratio. Window [as_of - window_days, as_of], BOTH bounds inclusive."""
    window_start = as_of - timedelta(days=window_days)
    window_end = as_of
    earned = 0
    agent_policies = [p for p in DB.policies.values() if p["agent_id"] == agent_id]
    in_window = []
    for p in agent_policies:
        if window_start <= p["inception_at"] <= window_end:
            in_window.append(p)
            earned += earned_in_window(p, window_start, window_end)
    incurred = 0
    in_window_ids = {p["id"] for p in in_window}
    for c in DB.claims.values():
        if c["policy_id"] in in_window_ids and window_start <= c["reported_at"] <= window_end:
            incurred += c["incurred_amount_cents"]
    return earned, incurred


def trailing_loss_ratio(agent_id, as_of):
    earned, incurred = trailing_earned_and_incurred(agent_id, as_of)
    if earned == 0:
        return 0.0, 0
    return round4(Decimal(incurred) / Decimal(earned)), earned


def find_covering_schedule(agent_id, lob, policy_created_at):
    """The agent's ACTIVE schedule for lob whose window covers policy_created_at."""
    for s in DB.schedules.values():
        if s["agent_id"] != agent_id or s["status"] != "ACTIVE":
            continue
        if s["line_of_business"] != lob:
            continue
        if s["effective_start"] <= policy_created_at and (
            s["effective_end"] is None or policy_created_at < s["effective_end"]
        ):
            return s
    return None


def pick_covering_publication(product_id):
    """Earliest-published PUBLISHED publication covering now for the product.

    Tie-break: lowest published_at, then publication created_at ASC.
    Returns None when no covering publication exists.
    """
    t = now()
    candidates = [
        p for p in DB.publications.values()
        if p["product_id"] == product_id
        and p["status"] == "PUBLISHED"
        and p["effective_start"] <= t < p["effective_end"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: (p["published_at"] or p["created_at"], p["created_at"]))
    return candidates[0]


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _handle_404(_e):
    return error("ERR_NOT_FOUND", 404, "Route not found")


@app.errorhandler(405)
def _handle_405(_e):
    return error("ERR_NOT_FOUND", 404, "Route not found")


# ---------------------------------------------------------------------------
# Logical clock (test-driving; outside the public business surface)
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    require_role("CarrierAdmin")
    body = get_body(required=True)
    to = req_dt(body, "to_iso8601")
    DB.clock = to
    return success({"current_utc": iso(DB.clock)}, 200)


# ---------------------------------------------------------------------------
# CarrierProduct
# ---------------------------------------------------------------------------

@app.post("/products")
def create_product():
    require_role("RatingManager")
    body = get_body(required=True)
    product_code = req_str(body, "product_code")
    lob = req_enum(body, "line_of_business", {"AUTO", "HOME"})
    state_code = req_str(body, "state_code")
    channel = req_enum(body, "channel_availability", {"DIRECT", "AGENT", "BOTH"})
    coverage_rates = body.get("coverage_rates")
    if not isinstance(coverage_rates, dict):
        raise_err("ERR_INVALID_REQUEST", "coverage_rates must be an object")
    min_premium_cents = req_int(body, "min_premium_cents", minimum=0)
    direct_discount_pct = opt_num(body, "direct_discount_pct", 0)
    agent_load_pct = opt_num(body, "agent_load_pct", 0)
    bundle_credit_pct = opt_num(body, "bundle_credit_pct", 0)
    direct_cap = opt_int(body, "direct_channel_max_premium_cents", None)
    bundle_eligible = opt_bool(body, "bundle_eligible", False)
    p = new_entity()
    p.update({
        "product_code": product_code,
        "line_of_business": lob,
        "state_code": state_code,
        "channel_availability": channel,
        "coverage_rates": coverage_rates,
        "direct_discount_pct": direct_discount_pct,
        "agent_load_pct": agent_load_pct,
        "bundle_credit_pct": bundle_credit_pct,
        "min_premium_cents": min_premium_cents,
        "direct_channel_max_premium_cents": direct_cap,
        "bundle_eligible": bundle_eligible,
        "status": "DRAFT",
    })
    DB.products[p["id"]] = p
    return success(ser_product(p), 201)


@app.get("/products")
def list_products():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    items = list(DB.products.values())
    f_ch = request.args.get("channel_availability")
    f_status = request.args.get("status")
    f_state = request.args.get("state_code")
    if f_ch:
        items = [p for p in items if p["channel_availability"] == f_ch]
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    if f_state:
        items = [p for p in items if p["state_code"] == f_state]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_product(p) for p in page], 200, pagination=meta)


@app.get("/products/<pid>")
def get_product(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    p = get_or_404(DB.products, pid, "product")
    return success(ser_product(p), 200)


@app.post("/products/<pid>/activate")
def activate_product(pid):
    require_role("RatingManager")
    p = get_or_404(DB.products, pid, "product")
    if p["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT product can be activated")
    if not p["coverage_rates"]:
        raise_err("ERR_INVALID_REQUEST", "coverage_rates must be non-empty to activate")
    p["status"] = "ACTIVE"
    touch(p)
    return success(ser_product(p), 200)


@app.post("/products/<pid>/withdraw")
def withdraw_product(pid):
    require_role("RatingManager")
    p = get_or_404(DB.products, pid, "product")
    if p["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE product can be withdrawn")
    for q in DB.quotes.values():
        if q["product_id"] == pid and quote_status(q) in ("QUOTED", "REFERRED_TO_AGENT", "AGENT_QUOTED"):
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Product cannot be withdrawn while in-flight quotes reference it")
    p["status"] = "WITHDRAWN"
    touch(p)
    return success(ser_product(p), 200)


@app.get("/products/<pid>/rate-feed-publications")
def list_product_feed_publications(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.products, pid, "product")
    items = [p for p in DB.publications.values() if p["product_id"] == pid]
    f_status = request.args.get("status")
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_publication(p) for p in page], 200, pagination=meta)


# ---------------------------------------------------------------------------
# ComparativeRater
# ---------------------------------------------------------------------------

@app.post("/raters")
def create_rater():
    require_role("RatingManager")
    body = get_body(required=True)
    rater_code = req_str(body, "rater_code")
    display_name = req_str(body, "display_name")
    feed_format_version = req_str(body, "feed_format_version")
    lob = req_enum(body, "accepted_line_of_business", {"AUTO", "HOME"})
    for r in DB.raters.values():
        if r["rater_code"] == rater_code:
            raise_err("ERR_DUPLICATE_RATER_CODE", f"rater_code {rater_code!r} already registered")
    r = new_entity()
    r.update({
        "rater_code": rater_code,
        "display_name": display_name,
        "feed_format_version": feed_format_version,
        "accepted_line_of_business": lob,
    })
    DB.raters[r["id"]] = r
    return success(ser_rater(r), 201)


@app.get("/raters")
def list_raters():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    items = sort_created(list(DB.raters.values()))
    page, meta = paginate(items)
    return success([ser_rater(r) for r in page], 200, pagination=meta)


@app.get("/raters/<rid>")
def get_rater(rid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    r = get_or_404(DB.raters, rid, "rater")
    return success(ser_rater(r), 200)


# ---------------------------------------------------------------------------
# RateFeedPublication
# ---------------------------------------------------------------------------

FEED_GAP = timedelta(hours=24)


@app.post("/raters/<rid>/rate-feed-publications")
def create_feed_publication(rid):
    require_role("RatingManager")
    rater = get_or_404(DB.raters, rid, "rater")
    body = get_body(required=True)
    product_id = req_str(body, "product_id")
    effective_start = req_dt(body, "effective_start")
    effective_end = req_dt(body, "effective_end")
    rate_table_payload = body.get("rate_table_payload")
    if rate_table_payload is None:
        raise_err("ERR_INVALID_REQUEST", "rate_table_payload is required")
    expected_rater_version = body.get("expected_rater_version")
    if not _is_int(expected_rater_version):
        raise_err("ERR_INVALID_REQUEST", "expected_rater_version is required and must be an integer")
    if effective_end <= effective_start:
        raise_err("ERR_INVALID_REQUEST", "effective_end must be after effective_start")
    # Existence (priority 5)
    product = get_or_404(DB.products, product_id, "product")
    # OCC (priority: per §2.7; surface before temporal/referential business rules)
    if expected_rater_version != rater["version"]:
        raise_err("ERR_STALE_VERSION",
                  f"expected_rater_version {expected_rater_version} != rater version {rater['version']}")
    # Temporal rules (priority 8) — strict overlap first, then 24h gap
    siblings = [
        p for p in DB.publications.values()
        if p["rater_id"] == rid and p["product_id"] == product_id
        and p["status"] in ("DRAFT", "PUBLISHED")
    ]
    for s in siblings:
        # strict overlap on half-open intervals
        if effective_start < s["effective_end"] and s["effective_start"] < effective_end:
            raise_err("ERR_FEED_WINDOW_OVERLAP",
                      "New publication window strictly overlaps an existing DRAFT/PUBLISHED window")
    for s in siblings:
        # gap on both sides: new window [ns, ne) vs sibling [ss, se)
        if effective_end <= s["effective_start"]:
            gap = s["effective_start"] - effective_end
        else:  # s["effective_end"] <= effective_start (no overlap survived the check above)
            gap = effective_start - s["effective_end"]
        if gap < FEED_GAP:
            raise_err("ERR_FEED_WINDOW_GAP_VIOLATION",
                      "Non-overlapping publication window leaves < 24h gap to a sibling window")
    # Referential (priority 9): product must be ACTIVE at creation time
    if product["status"] != "ACTIVE":
        raise_err("ERR_PRODUCT_NOT_PUBLISHABLE",
                  "Feed publications can only be created for ACTIVE products")
    pub = new_entity()
    pub.update({
        "rater_id": rid,
        "product_id": product_id,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "rate_table_payload": rate_table_payload,
        "status": "DRAFT",
        "published_at": None,
    })
    DB.publications[pub["id"]] = pub
    touch(rater)
    return success(ser_publication(pub), 201)


@app.get("/raters/<rid>/rate-feed-publications")
def list_rater_feed_publications(rid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.raters, rid, "rater")
    items = [p for p in DB.publications.values() if p["rater_id"] == rid]
    f_status = request.args.get("status")
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_publication(p) for p in page], 200, pagination=meta)


@app.get("/rate-feed-publications/<pid>")
def get_feed_publication(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    p = get_or_404(DB.publications, pid, "publication")
    return success(ser_publication(p), 200)


def _flag_quotes_stale_for_publication(pub_id):
    for q in DB.quotes.values():
        if q["rate_feed_publication_id"] == pub_id and q["status"] in ("QUOTED", "AGENT_QUOTED"):
            q["rate_stale"] = True
            touch(q)


@app.post("/rate-feed-publications/<pid>/publish")
def publish_feed_publication(pid):
    require_role("RatingManager")
    pub = get_or_404(DB.publications, pid, "publication")
    if pub["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT publication can be published")
    product = get_or_404(DB.products, pub["product_id"], "product")
    if product["status"] != "ACTIVE":
        raise_err("ERR_PRODUCT_NOT_ACTIVE", "Product must be ACTIVE to publish")
    # Cascade hop 1: supersede prior PUBLISHED publication for the same pair.
    prior = None
    for p in DB.publications.values():
        if (p["id"] != pub["id"] and p["rater_id"] == pub["rater_id"]
                and p["product_id"] == pub["product_id"] and p["status"] == "PUBLISHED"):
            prior = p
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
        # Cascade hop 2: flag dependent quotes stale.
        _flag_quotes_stale_for_publication(prior["id"])
    pub["status"] = "PUBLISHED"
    pub["published_at"] = now()
    touch(pub)
    return success(ser_publication(pub), 200)


@app.post("/rate-feed-publications/<pid>/recall")
def recall_feed_publication(pid):
    require_role("RatingManager")
    pub = get_or_404(DB.publications, pid, "publication")
    if pub["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT or PUBLISHED publication can be recalled")
    was_published = pub["status"] == "PUBLISHED"
    pub["status"] = "RECALLED"
    touch(pub)
    if was_published:
        _flag_quotes_stale_for_publication(pub["id"])
    return success(ser_publication(pub), 200)


# ---------------------------------------------------------------------------
# Agent + Appointments + Commission Schedules + Statements + Reviews + Payouts
# ---------------------------------------------------------------------------

@app.post("/agents")
def create_agent():
    require_role("CarrierAdmin")
    body = get_body(required=True)
    agency_name = req_str(body, "agency_name")
    principal_name = req_str(body, "principal_name")
    resident_state_code = req_str(body, "resident_state_code")
    a = new_entity()
    a.update({
        "agency_name": agency_name,
        "principal_name": principal_name,
        "resident_state_code": resident_state_code,
        "status": "APPLICANT",
        "terminated_reason": None,
    })
    DB.agents[a["id"]] = a
    return success(ser_agent(a), 201)


@app.get("/agents")
def list_agents():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    items = list(DB.agents.values())
    f_status = request.args.get("status")
    f_state = request.args.get("state_code")
    if f_status:
        items = [a for a in items if a["status"] == f_status]
    if f_state:
        items = [a for a in items if a["resident_state_code"] == f_state]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_agent(a) for a in page], 200, pagination=meta)


@app.get("/agents/<aid>")
def get_agent(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    a = get_or_404(DB.agents, aid, "agent")
    user_id, role = get_auth()
    check_ownership(user_id, role, aid)
    return success(ser_agent(a), 200)


def _terminate_agent(agent, reason):
    """§3.6 agent termination cascade: appointments -> schedules -> statements."""
    agent["status"] = "TERMINATED"
    agent["terminated_reason"] = reason
    touch(agent)
    # Hop 1: every ACTIVE appointment -> TERMINATED with reason AGENT_TERMINATED
    for appt in DB.appointments.values():
        if appt["agent_id"] == agent["id"] and appointment_status(appt) == "ACTIVE":
            appt["status"] = "TERMINATED"
            appt["terminated_reason"] = "AGENT_TERMINATED"
            touch(appt)
    # Hop 2: every ACTIVE schedule whose LOB no longer has any ACTIVE appointment -> VOIDED
    for s in DB.schedules.values():
        if s["agent_id"] != agent["id"] or s["status"] != "ACTIVE":
            continue
        if not agent_has_any_active_appointment(agent["id"]) or not any(
            appointment_status(a) == "ACTIVE"
            and a["agent_id"] == agent["id"]
            and a["line_of_business"] == s["line_of_business"]
            for a in DB.appointments.values()
        ):
            s["status"] = "VOIDED"
            touch(s)
    # Hop 3: every DRAFT statement -> STALE
    for st in DB.statements.values():
        if st["agent_id"] == agent["id"] and st["status"] == "DRAFT":
            st["status"] = "STALE"
            touch(st)


@app.post("/agents/<aid>/appoint")
def appoint_agent(aid):
    require_role("UnderwritingReviewer")
    a = get_or_404(DB.agents, aid, "agent")
    if a["status"] != "APPLICANT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPLICANT agent can be appointed")
    if not agent_has_any_active_appointment(aid):
        raise_err("ERR_AGENT_NOT_APPOINTED_IN_STATE",
                  "Agent must hold at least one ACTIVE appointment to be appointed")
    a["status"] = "APPOINTED"
    touch(a)
    return success(ser_agent(a), 200)


@app.post("/agents/<aid>/suspend")
def suspend_agent(aid):
    require_role("UnderwritingReviewer")
    a = get_or_404(DB.agents, aid, "agent")
    if a["status"] != "APPOINTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an APPOINTED agent can be suspended")
    a["status"] = "SUSPENDED"
    touch(a)
    return success(ser_agent(a), 200)


@app.post("/agents/<aid>/reinstate")
def reinstate_agent(aid):
    require_role("UnderwritingReviewer")
    a = get_or_404(DB.agents, aid, "agent")
    if a["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a SUSPENDED agent can be reinstated")
    if not agent_has_any_active_appointment(aid):
        raise_err("ERR_AGENT_NOT_APPOINTED_IN_STATE",
                  "Agent must hold at least one ACTIVE appointment to be reinstated")
    a["status"] = "APPOINTED"
    touch(a)
    return success(ser_agent(a), 200)


@app.post("/agents/<aid>/terminate")
def terminate_agent(aid):
    require_role("UnderwritingReviewer")
    a = get_or_404(DB.agents, aid, "agent")
    if a["status"] not in ("APPOINTED", "SUSPENDED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an APPOINTED or SUSPENDED agent can be terminated")
    # Money rule (priority 10): no PLACED bundle placements
    for pl in DB.placements.values():
        if pl["agent_id"] == aid and pl["status"] == "PLACED":
            raise_err("ERR_AGENT_HAS_ACTIVE_PLACEMENTS",
                      "Agent holds PLACED bundle placements")
    body = get_body(required=False)
    reason = opt_str(body, "reason", None)
    _terminate_agent(a, reason)
    return success(ser_agent(a), 200)


# ---- Appointments -----------------------------------------------------------

@app.post("/agents/<aid>/appointments")
def create_appointment(aid):
    require_role("UnderwritingReviewer")
    get_or_404(DB.agents, aid, "agent")
    body = get_body(required=True)
    state_code = req_str(body, "state_code")
    lob = req_enum(body, "line_of_business", {"AUTO", "HOME"})
    effective_start = req_dt(body, "effective_start")
    effective_end = opt_dt(body, "effective_end", None)
    if effective_end is not None and effective_end <= effective_start:
        raise_err("ERR_INVALID_REQUEST", "effective_end must be after effective_start")
    # Half-open overlap with existing ACTIVE appointments of (agent, state, line)
    for ap in DB.appointments.values():
        if (ap["agent_id"] == aid and ap["state_code"] == state_code
                and ap["line_of_business"] == lob
                and appointment_status(ap) == "ACTIVE"):
            ap_end = ap["effective_end"] if ap["effective_end"] is not None else None
            new_end = effective_end
            # overlap if (new_start < ap_end or ap_end is None) and (ap_start < new_end or new_end is None)
            left = (ap_end is None) or (effective_start < ap_end)
            right = (new_end is None) or (ap["effective_start"] < new_end)
            if left and right:
                raise_err("ERR_APPOINTMENT_WINDOW_OVERLAP",
                          "New appointment window intersects an existing ACTIVE appointment")
    a = new_entity()
    a.update({
        "agent_id": aid,
        "state_code": state_code,
        "line_of_business": lob,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "ACTIVE",
        "terminated_reason": None,
    })
    DB.appointments[a["id"]] = a
    return success(ser_appointment(a), 201)


@app.get("/agents/<aid>/appointments")
def list_agent_appointments(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.agents, aid, "agent")
    items = [a for a in DB.appointments.values() if a["agent_id"] == aid]
    f_status = request.args.get("status")
    if f_status:
        items = [a for a in items if appointment_status(a) == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_appointment(a) for a in page], 200, pagination=meta)


@app.get("/appointments/<aid>")
def get_appointment(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    a = get_or_404(DB.appointments, aid, "appointment")
    return success(ser_appointment(a), 200)


@app.post("/appointments/<aid>/terminate")
def terminate_appointment(aid):
    require_role("UnderwritingReviewer")
    ap = get_or_404(DB.appointments, aid, "appointment")
    if appointment_status(ap) != "ACTIVE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE appointment can be terminated")
    body = get_body(required=False)
    reason = opt_str(body, "reason", None)
    ap["status"] = "TERMINATED"
    ap["terminated_reason"] = reason
    touch(ap)
    return success(ser_appointment(ap), 200)


# ---- Commission Schedules ---------------------------------------------------

@app.post("/agents/<aid>/commission-schedules")
def create_commission_schedule(aid):
    require_role("CarrierAdmin")
    agent = get_or_404(DB.agents, aid, "agent")
    body = get_body(required=True)
    lob = req_enum(body, "line_of_business", {"AUTO", "HOME"})
    effective_start = req_dt(body, "effective_start")
    effective_end = opt_dt(body, "effective_end", None)
    tiers = body.get("tiers")
    if not isinstance(tiers, list) or len(tiers) == 0:
        raise_err("ERR_INVALID_REQUEST", "tiers must be a non-empty array")
    for t in tiers:
        if not isinstance(t, dict):
            raise_err("ERR_INVALID_REQUEST", "each tier must be an object")
        up_to = t.get("up_to_cents")
        if up_to is not None and not _is_int(up_to):
            raise_err("ERR_INVALID_REQUEST", "tier up_to_cents must be an integer or null")
        rate = t.get("rate_pct")
        if not _is_num(rate):
            raise_err("ERR_INVALID_REQUEST", "tier rate_pct must be a number")
    contingent = body.get("contingent_bonus_eligible")
    if not isinstance(contingent, bool):
        raise_err("ERR_INVALID_REQUEST", "contingent_bonus_eligible must be a boolean")
    expected_agent_version = body.get("expected_agent_version")
    if not _is_int(expected_agent_version):
        raise_err("ERR_INVALID_REQUEST", "expected_agent_version is required and must be an integer")
    if expected_agent_version != agent["version"]:
        raise_err("ERR_STALE_VERSION",
                  f"expected_agent_version {expected_agent_version} != agent version {agent['version']}")
    # Supersede prior ACTIVE schedule for the same (agent, line_of_business)
    for s in DB.schedules.values():
        if s["agent_id"] == aid and s["line_of_business"] == lob and s["status"] == "ACTIVE":
            s["status"] = "SUPERSEDED"
            touch(s)
    s = new_entity()
    s.update({
        "agent_id": aid,
        "line_of_business": lob,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "tiers": tiers,
        "contingent_bonus_eligible": contingent,
        "status": "ACTIVE",
    })
    DB.schedules[s["id"]] = s
    touch(agent)
    return success(ser_schedule(s), 201)


@app.get("/agents/<aid>/commission-schedules")
def list_agent_commission_schedules(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.agents, aid, "agent")
    items = [s for s in DB.schedules.values() if s["agent_id"] == aid]
    f_status = request.args.get("status")
    if f_status:
        items = [s for s in items if s["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_schedule(s) for s in page], 200, pagination=meta)


@app.get("/commission-schedules/<sid>")
def get_commission_schedule(sid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    s = get_or_404(DB.schedules, sid, "schedule")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, s["agent_id"])
    return success(ser_schedule(s), 200)


# ---- Consumers --------------------------------------------------------------

@app.post("/consumers")
def create_consumer():
    require_role("Anonymous")
    body = get_body(required=True)
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    date_of_birth = req_str(body, "date_of_birth")
    home_state_code = req_str(body, "home_state_code")
    for c in DB.consumers.values():
        if c["email"] == email:
            raise_err("ERR_DUPLICATE_CONSUMER_EMAIL", f"email {email!r} already registered")
    c = new_entity()
    c.update({
        "email": email,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "home_state_code": home_state_code,
    })
    DB.consumers[c["id"]] = c
    return success(ser_consumer(c), 201)


@app.get("/consumers")
def list_consumers():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "System")
    items = list(DB.consumers.values())
    f_state = request.args.get("home_state_code")
    if f_state:
        items = [c for c in items if c["home_state_code"] == f_state]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_consumer(c) for c in page], 200, pagination=meta)


@app.get("/consumers/<cid>")
def get_consumer(cid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    c = get_or_404(DB.consumers, cid, "consumer")
    user_id, role = get_auth()
    check_ownership(user_id, role, cid)
    return success(ser_consumer(c), 200)


# ---- Quotes -----------------------------------------------------------------

def _validate_coverages(coverages):
    if not isinstance(coverages, list) or len(coverages) == 0:
        raise_err("ERR_INVALID_REQUEST", "coverages must be a non-empty array")
    for cov in coverages:
        if not isinstance(cov, dict):
            raise_err("ERR_INVALID_REQUEST", "each coverage must be an object")
        code = cov.get("coverage_code")
        tier = cov.get("tier")
        if not isinstance(code, str) or not code:
            raise_err("ERR_INVALID_REQUEST", "coverage.coverage_code must be a non-empty string")
        if not isinstance(tier, str) or not tier:
            raise_err("ERR_INVALID_REQUEST", "coverage.tier must be a non-empty string")


@app.post("/quotes")
def create_quote():
    user_id, role = require_role("Consumer", "Agent")
    body = get_body(required=True)
    consumer_id = req_str(body, "consumer_id")
    product_id = req_str(body, "product_id")
    channel = req_enum(body, "channel", {"DIRECT", "AGENT"})
    coverages = body.get("coverages")
    _validate_coverages(coverages)
    agent_id = opt_str(body, "agent_id", None)
    bundled = opt_bool(body, "bundled_home_intended", False)
    telematics = opt_bool(body, "telematics_opt_in", False)
    # Existence (priority 5): left-to-right — consumer_id then product_id then agent_id
    get_or_404(DB.consumers, consumer_id, "consumer")
    get_or_404(DB.products, product_id, "product")
    if agent_id is not None:
        get_or_404(DB.agents, agent_id, "agent")
    # Channel binding (priority 9 / ownership — creation-time binding rules)
    if channel == "AGENT":
        if agent_id is None:
            raise_err("ERR_AGENT_MISMATCH", "AGENT-channel quote requires agent_id")
    # Identity binding for entity-backed callers (§3.3)
    if role == "Consumer":
        if consumer_id != user_id:
            raise_err("ERR_OWNERSHIP_MISMATCH",
                      "Consumer callers may only create quotes with consumer_id == themselves")
        if channel != "DIRECT":
            # Consumer may only create DIRECT quotes; creating AGENT-channel with
            # someone else's agent_id (or own agent_id) is rejected as a mismatch.
            raise_err("ERR_AGENT_MISMATCH",
                      "Consumer callers may only create DIRECT-channel quotes")
    if role == "Agent":
        if channel != "AGENT":
            raise_err("ERR_AGENT_MISMATCH",
                      "Agent callers may only create AGENT-channel quotes")
        if agent_id != user_id:
            raise_err("ERR_OWNERSHIP_MISMATCH",
                      "Agent callers may only create quotes with agent_id == themselves")
    q = new_entity()
    q.update({
        "consumer_id": consumer_id,
        "product_id": product_id,
        "agent_id": agent_id,
        "channel": channel,
        "coverages": coverages,
        "bundled_home_intended": bundled,
        "telematics_opt_in": telematics,
        "status": "DRAFT",
        "quoted_premium_cents": None,
        "quoted_at": None,
        "expires_at": None,
        "rate_stale": False,
        "referral_snapshot": None,
        "rate_feed_publication_id": None,
    })
    DB.quotes[q["id"]] = q
    return success(ser_quote(q), 201)


@app.get("/quotes")
def list_quotes():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    items = list(DB.quotes.values())
    f_consumer = request.args.get("consumer_id")
    f_product = request.args.get("product_id")
    f_agent = request.args.get("agent_id")
    f_feed = request.args.get("rate_feed_publication_id")
    f_channel = request.args.get("channel")
    f_status = request.args.get("status")
    if f_consumer:
        items = [q for q in items if q["consumer_id"] == f_consumer]
    if f_product:
        items = [q for q in items if q["product_id"] == f_product]
    if f_agent:
        items = [q for q in items if q["agent_id"] == f_agent]
    if f_feed:
        items = [q for q in items if q["rate_feed_publication_id"] == f_feed]
    if f_channel:
        items = [q for q in items if q["channel"] == f_channel]
    if f_status:
        items = [q for q in items if quote_status(q) == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_quote(q) for q in page], 200, pagination=meta)


@app.get("/quotes/<qid>")
def get_quote(qid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    q = get_or_404(DB.quotes, qid, "quote")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, q["agent_id"])
    elif role == "Consumer":
        check_ownership(user_id, role, q["consumer_id"])
    return success(ser_quote(q), 200)


def _check_agent_standing(agent_id, product):
    """Compliance checks for agent-channel quote actions.

    Returns nothing on success; raises ERR_AGENT_TERMINATED /
    ERR_AGENT_NOT_APPOINTED_IN_STATE on failure.
    """
    agent = DB.agents.get(agent_id)
    if agent is None:
        raise_err("ERR_NOT_FOUND", f"agent {agent_id} not found")
    if agent["status"] != "APPOINTED":
        raise_err("ERR_AGENT_TERMINATED",
                  "Agent must be APPOINTED (non-TERMINATED) for agent-channel actions")
    if not has_active_appointment(agent_id, product["state_code"], product["line_of_business"]):
        raise_err("ERR_AGENT_NOT_APPOINTED_IN_STATE",
                  "Agent must hold an ACTIVE appointment for (product.state_code, product.line_of_business)")


def _price_and_stamp(quote, product):
    premium = channel_quote_premium(
        product, quote["channel"], quote["coverages"], quote["bundled_home_intended"]
    )
    quote["quoted_premium_cents"] = premium
    quote["quoted_at"] = now()
    quote["expires_at"] = now() + timedelta(days=30)
    quote["rate_stale"] = False
    return premium


@app.post("/quotes/<qid>/submit")
def submit_quote(qid):
    user_id, role = require_role("Consumer", "Agent")
    q = get_or_404(DB.quotes, qid, "quote")
    # Ownership (priority 3) — entity-backed caller must own the quote
    if role == "Consumer":
        check_ownership(user_id, role, q["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, q["agent_id"])
    # State (priority 6)
    if q["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT quote can be submitted")
    product = get_or_404(DB.products, q["product_id"], "product")
    if product["status"] != "ACTIVE":
        raise_err("ERR_PRODUCT_NOT_ACTIVE", "Product must be ACTIVE to submit")
    # Compliance (priority 7) — agent standing for agent-channel
    if q["channel"] == "AGENT":
        _check_agent_standing(q["agent_id"], product)
        # Feed pin (priority 6 lazy state)
        pub = pick_covering_publication(q["product_id"])
        if pub is None:
            raise_err("ERR_FEED_NOT_PUBLISHED",
                      "No PUBLISHED RateFeedPublication covers now for this product")
        q["rate_feed_publication_id"] = pub["id"]
    # Channel availability (priority 9)
    if product["channel_availability"] not in (q["channel"], "BOTH"):
        raise_err("ERR_CHANNEL_NOT_AVAILABLE",
                  f"Product channel_availability does not include {q['channel']}")
    # Compute premium
    premium = _price_and_stamp(q, product)
    # Money rule (priority 10) — DIRECT premium cap
    if (q["channel"] == "DIRECT"
            and product["direct_channel_max_premium_cents"] is not None
            and premium > product["direct_channel_max_premium_cents"]):
        # roll back the stamp so a failed submit leaves the quote untouched
        q["quoted_premium_cents"] = None
        q["quoted_at"] = None
        q["expires_at"] = None
        q["rate_feed_publication_id"] = None
        raise_err("ERR_PREMIUM_CAP_EXCEEDED",
                  "DIRECT-channel premium exceeds product.direct_channel_max_premium_cents")
    q["status"] = "QUOTED"
    touch(q)
    return success(ser_quote(q), 200)


@app.post("/quotes/<qid>/re-rate")
def re_rate_quote(qid):
    user_id, role = require_role("Consumer", "Agent")
    q = get_or_404(DB.quotes, qid, "quote")
    if role == "Consumer":
        check_ownership(user_id, role, q["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, q["agent_id"])
    current = q["status"]
    if current == "QUOTED":
        q["status"] = "DRAFT"
    elif current == "AGENT_QUOTED":
        # agent-side re-rate preserves the referral
        q["status"] = "REFERRED_TO_AGENT"
    else:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a QUOTED or AGENT_QUOTED quote can be re-rated")
    q["quoted_premium_cents"] = None
    q["quoted_at"] = None
    q["expires_at"] = None
    q["rate_stale"] = False
    q["rate_feed_publication_id"] = None
    touch(q)
    return success(ser_quote(q), 200)


@app.post("/quotes/<qid>/refer-to-agent")
def refer_to_agent(qid):
    user_id, role = require_role("Consumer")
    q = get_or_404(DB.quotes, qid, "quote")
    check_ownership(user_id, role, q["consumer_id"])
    body = get_body(required=True)
    agent_id = req_str(body, "agent_id")
    if q["status"] != "QUOTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a QUOTED quote can be referred to an agent")
    if q["channel"] != "DIRECT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a DIRECT-channel quote can be referred to an agent")
    agent = get_or_404(DB.agents, agent_id, "agent")
    product = get_or_404(DB.products, q["product_id"], "product")
    if agent["status"] != "APPOINTED":
        raise_err("ERR_AGENT_TERMINATED", "Target agent must be APPOINTED")
    if not has_active_appointment(agent_id, product["state_code"], product["line_of_business"]):
        raise_err("ERR_AGENT_NOT_APPOINTED_IN_STATE",
                  "Target agent must hold an ACTIVE appointment for (state, line)")
    q["agent_id"] = agent_id
    q["channel"] = "AGENT"
    q["referral_snapshot"] = {
        "coverages": q["coverages"],
        "quoted_premium_cents": q["quoted_premium_cents"],
    }
    q["status"] = "REFERRED_TO_AGENT"
    touch(q)
    return success(ser_quote(q), 200)


@app.post("/quotes/<qid>/agent-quote")
def agent_quote(qid):
    user_id, role = require_role("Agent")
    q = get_or_404(DB.quotes, qid, "quote")
    check_ownership(user_id, role, q["agent_id"])
    body = get_body(required=False)
    new_coverages = body.get("coverages")
    if new_coverages is not None:
        _validate_coverages(new_coverages)
    if q["status"] != "REFERRED_TO_AGENT":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a REFERRED_TO_AGENT quote can be agent-quoted")
    product = get_or_404(DB.products, q["product_id"], "product")
    _check_agent_standing(q["agent_id"], product)
    pub = pick_covering_publication(q["product_id"])
    if pub is None:
        raise_err("ERR_FEED_NOT_PUBLISHED",
                  "No PUBLISHED RateFeedPublication covers now for this product")
    # Adopt supplied coverages when different from the snapshot; reuse snapshot otherwise
    if new_coverages is not None and new_coverages != q["referral_snapshot"]["coverages"]:
        q["coverages"] = new_coverages
    else:
        q["coverages"] = q["referral_snapshot"]["coverages"]
    q["rate_feed_publication_id"] = pub["id"]
    _price_and_stamp(q, product)
    q["status"] = "AGENT_QUOTED"
    touch(q)
    return success(ser_quote(q), 200)


@app.post("/quotes/<qid>/bind")
def bind_quote(qid):
    user_id, role = require_role("Consumer", "Agent")
    q = get_or_404(DB.quotes, qid, "quote")
    current = q["status"]
    # Ownership (priority 3, §2.8) precedes state-transition legality (6).
    if role == "Consumer":
        check_ownership(user_id, role, q["consumer_id"])
    else:
        check_ownership(user_id, role, q["agent_id"])
    # Channel/leg state-legality for consumer vs agent legs.
    # PRD §3.3: "A `Consumer` binds a direct quote from `QUOTED` ... the quote
    # must still be direct-channel (`ERR_INVALID_STATE_TRANSITION`). An `Agent`
    # binds from `AGENT_QUOTED`." Terminal states (BOUND/WITHDRAWN) have no
    # bind leg for either role.
    if role == "Consumer":
        if current == "DRAFT":
            raise_err("ERR_INVALID_STATE_TRANSITION", "Cannot bind a DRAFT quote")
        if current in ("BOUND", "WITHDRAWN"):
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      f"Cannot bind a quote in {current}")
        if current != "QUOTED":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Consumer-side bind applies only to DIRECT QUOTED quotes")
        if q["channel"] != "DIRECT":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Consumer-side bind requires the quote still be direct-channel")
    else:  # Agent
        if current in ("DRAFT", "BOUND", "WITHDRAWN"):
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      f"Cannot bind a quote in {current}")
        if current != "AGENT_QUOTED":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Agent-side bind applies only to AGENT_QUOTED quotes")
    # Lazy-state checks (priority 6)
    if q["expires_at"] is not None and now() >= q["expires_at"]:
        raise_err("ERR_QUOTE_EXPIRED", "Logical clock now >= quote.expires_at")
    if q["rate_stale"]:
        raise_err("ERR_RATE_STALE", "Pinned feed publication was superseded or recalled")
    product = get_or_404(DB.products, q["product_id"], "product")
    if role == "Agent":
        _check_agent_standing(q["agent_id"], product)
    # Bind
    quoted = q["quoted_premium_cents"]
    written = quoted
    upfront_discount = 0
    if q["telematics_opt_in"] and q["channel"] == "DIRECT":
        upfront_discount = rhu(Decimal(quoted) * DIRECT_TELEMATICS_UPFRONT_PCT)
        written = quoted - upfront_discount
    q["status"] = "BOUND"
    touch(q)
    p = new_entity()
    p.update({
        "quote_id": q["id"],
        "consumer_id": q["consumer_id"],
        "agent_id": q["agent_id"] if q["channel"] == "AGENT" else None,
        "product_id": q["product_id"],
        "channel": q["channel"],
        "inception_at": now(),
        "term_days": 365,
        "written_premium_cents": written,
        "status": "IN_FORCE",
        "cancelled_at": None,
        "earned_premium_cents": written,
        "unearned_premium_cents": 0,
        "per_policy_commission_cents": None,
        "clawback_cents": 0,
    })
    DB.policies[p["id"]] = p
    if q["telematics_opt_in"]:
        e = new_entity()
        e.update({
            "policy_id": p["id"],
            "channel": p["channel"],
            "status": "ENROLLED",
            "driving_score": None,
            "upfront_discount_cents": upfront_discount,
            "discount_pct_applied": None,
            "adjustment_cents": None,
        })
        DB.enrollments[e["id"]] = e
    return success(ser_policy(p), 200)


@app.post("/quotes/<qid>/withdraw")
def withdraw_quote(qid):
    user_id, role = require_role("Consumer", "Agent")
    q = get_or_404(DB.quotes, qid, "quote")
    if role == "Consumer":
        check_ownership(user_id, role, q["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, q["agent_id"])
    if q["status"] in ("QUOTED", "REFERRED_TO_AGENT"):
        q["status"] = "WITHDRAWN"
        touch(q)
    elif q["status"] == "AGENT_QUOTED":
        # PRD §3.3: withdrawal from AGENT_QUOTED records no further field changes
        q["status"] = "WITHDRAWN"
    else:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  f"Cannot withdraw a quote in {q['status']}")
    return success(ser_quote(q), 200)


# ---- Policies ---------------------------------------------------------------

@app.get("/policies")
def list_policies():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    items = list(DB.policies.values())
    f_quote = request.args.get("quote_id")
    f_consumer = request.args.get("consumer_id")
    f_agent = request.args.get("agent_id")
    f_product = request.args.get("product_id")
    f_status = request.args.get("status")
    if f_quote:
        items = [p for p in items if p["quote_id"] == f_quote]
    if f_consumer:
        items = [p for p in items if p["consumer_id"] == f_consumer]
    if f_agent:
        items = [p for p in items if p["agent_id"] == f_agent]
    if f_product:
        items = [p for p in items if p["product_id"] == f_product]
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_policy(p) for p in page], 200, pagination=meta)


@app.get("/policies/<pid>")
def get_policy(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    p = get_or_404(DB.policies, pid, "policy")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, p["agent_id"])
    elif role == "Consumer":
        check_ownership(user_id, role, p["consumer_id"])
    return success(ser_policy(p), 200)


@app.post("/policies/<pid>/cancel")
def cancel_policy(pid):
    user_id, role = require_role("Consumer", "Agent", "CarrierAdmin")
    p = get_or_404(DB.policies, pid, "policy")
    if role == "Consumer":
        check_ownership(user_id, role, p["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, p["agent_id"])
    if p["status"] != "IN_FORCE":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an IN_FORCE policy can be cancelled")
    cancel_at = now()
    days = days_between(p["inception_at"], cancel_at)
    earned = rhu(Decimal(p["written_premium_cents"]) * days / p["term_days"])
    p["cancelled_at"] = cancel_at
    p["status"] = "CANCELLED"
    p["earned_premium_cents"] = earned
    p["unearned_premium_cents"] = p["written_premium_cents"] - earned
    touch(p)
    # Cascade: force ENROLLED/PARTICIPATING enrollment to OPTED_OUT; adjustment stays null
    for e in DB.enrollments.values():
        if e["policy_id"] == p["id"] and e["status"] in ("ENROLLED", "PARTICIPATING"):
            e["status"] = "OPTED_OUT"
            touch(e)
    return success(ser_policy(p), 200)


# ---- Claims -----------------------------------------------------------------

@app.post("/policies/<pid>/claims")
def create_claim(pid):
    require_role("CarrierAdmin")
    get_or_404(DB.policies, pid, "policy")
    body = get_body(required=True)
    claim_type = req_enum(body, "claim_type", {"COLLISION", "LIABILITY", "HOME_DAMAGE", "OTHER"})
    incurred = req_int(body, "incurred_amount_cents", minimum=0)
    c = new_entity()
    c.update({
        "policy_id": pid,
        "claim_type": claim_type,
        "incurred_amount_cents": incurred,
        "status": "REPORTED",
        "reported_at": now(),
    })
    DB.claims[c["id"]] = c
    return success(ser_claim(c), 201)


@app.get("/policies/<pid>/claims")
def list_policy_claims(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.policies, pid, "policy")
    items = [c for c in DB.claims.values() if c["policy_id"] == pid]
    f_status = request.args.get("status")
    if f_status:
        items = [c for c in items if c["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_claim(c) for c in page], 200, pagination=meta)


@app.get("/claims/<cid>")
def get_claim(cid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    c = get_or_404(DB.claims, cid, "claim")
    return success(ser_claim(c), 200)


@app.post("/claims/<cid>/close")
def close_claim(cid):
    require_role("CarrierAdmin")
    c = get_or_404(DB.claims, cid, "claim")
    if c["status"] != "REPORTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a REPORTED claim can be closed")
    c["status"] = "CLOSED"
    touch(c)
    return success(ser_claim(c), 200)


# ---- Telematics Enrollments -------------------------------------------------

@app.get("/policies/<pid>/telematics-enrollments")
def list_policy_enrollments(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.policies, pid, "policy")
    items = [e for e in DB.enrollments.values() if e["policy_id"] == pid]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_enrollment(e) for e in page], 200, pagination=meta)


@app.get("/telematics-enrollments/<eid>")
def get_enrollment(eid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    e = get_or_404(DB.enrollments, eid, "enrollment")
    return success(ser_enrollment(e), 200)


@app.post("/telematics-enrollments/<eid>/activate-device")
def activate_enrollment(eid):
    user_id, role = require_role("Consumer", "Agent")
    e = get_or_404(DB.enrollments, eid, "enrollment")
    policy = get_or_404(DB.policies, e["policy_id"], "policy")
    if role == "Consumer":
        check_ownership(user_id, role, policy["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, policy["agent_id"])
    if e["status"] != "ENROLLED":
        if policy["status"] != "IN_FORCE":
            # PRD §3.5: activation requires the policy IN_FORCE
            # (ERR_POLICY_NOT_IN_FORCE) — the lazy-state error reports when
            # cancellation has already forced the enrollment out of ENROLLED.
            raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an ENROLLED enrollment can be activated")
    if policy["status"] != "IN_FORCE":
        raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
    e["status"] = "PARTICIPATING"
    touch(e)
    return success(ser_enrollment(e), 200)


@app.post("/telematics-enrollments/<eid>/score")
def score_enrollment(eid):
    require_role("System")
    e = get_or_404(DB.enrollments, eid, "enrollment")
    body = get_body(required=True)
    score = req_int(body, "driving_score")
    if score < 0 or score > 100:
        raise_err("ERR_INVALID_REQUEST", "driving_score must be in [0, 100]")
    policy = get_or_404(DB.policies, e["policy_id"], "policy")
    if e["status"] != "PARTICIPATING":
        if policy["status"] != "IN_FORCE":
            # PRD §3.5: scoring requires the policy to remain IN_FORCE
            # (ERR_POLICY_NOT_IN_FORCE) — the lazy-state error reports when
            # cancellation has already forced the enrollment out of
            # PARTICIPATING.
            raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a PARTICIPATING enrollment can be scored")
    if policy["status"] != "IN_FORCE":
        raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
    quote = get_or_404(DB.quotes, policy["quote_id"], "quote")
    e["driving_score"] = score
    pct = score_table(score)
    e["discount_pct_applied"] = float(pct)
    final_premium = rhu(Decimal(quote["quoted_premium_cents"]) * (Decimal(1) - pct))
    e["adjustment_cents"] = final_premium - policy["written_premium_cents"]
    e["status"] = "SCORED"
    touch(e)
    # PRD §3.5: scoring refreshes the policy's updated_at
    policy["updated_at"] = now()
    return success(ser_enrollment(e), 200)


@app.post("/telematics-enrollments/<eid>/opt-out")
def opt_out_enrollment(eid):
    user_id, role = require_role("Consumer", "Agent")
    e = get_or_404(DB.enrollments, eid, "enrollment")
    policy = get_or_404(DB.policies, e["policy_id"], "policy")
    if role == "Consumer":
        check_ownership(user_id, role, policy["consumer_id"])
    elif role == "Agent":
        check_ownership(user_id, role, policy["agent_id"])
    if e["status"] not in ("ENROLLED", "PARTICIPATING"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an ENROLLED or PARTICIPATING enrollment can be opted out")
    # Explicit opt-out: DIRECT with upfront_discount > 0 debits back the discount;
    # AGENT opt-out sets adjustment_cents to 0.
    if e["channel"] == "DIRECT" and e["upfront_discount_cents"] > 0:
        e["adjustment_cents"] = e["upfront_discount_cents"]
    else:
        e["adjustment_cents"] = 0
    e["status"] = "OPTED_OUT"
    touch(e)
    return success(ser_enrollment(e), 200)


# ---- Commission Statements --------------------------------------------------

@app.post("/agents/<aid>/commission-statements")
def create_commission_statement(aid):
    require_role("CarrierAdmin")
    get_or_404(DB.agents, aid, "agent")
    body = get_body(required=True)
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end <= period_start:
        raise_err("ERR_INVALID_REQUEST", "period_end must be after period_start")
    # Temporal (priority 8): overlap with FINALIZED/PAID/CLAWED_BACK statements.
    # Per §2.8 the temporal-interval rule reports ahead of the remaining
    # body-shape "not in the future" window rule.
    for s in DB.statements.values():
        if s["agent_id"] != aid or s["status"] not in ("FINALIZED", "PAID", "CLAWED_BACK"):
            continue
        if period_start < s["period_end"] and s["period_start"] < period_end:
            raise_err("ERR_STATEMENT_PERIOD_OVERLAP",
                      "Statement window overlaps a FINALIZED/PAID/CLAWED_BACK statement")
    if period_end > now():
        raise_err("ERR_INVALID_REQUEST", "period_end must not be in the future")
    # Collect eligible policies: agent's bound policies with policy created_at
    # in [period_start, period_end), processed in created_at ASC (never by id).
    policies = [
        p for p in DB.policies.values()
        if p["agent_id"] == aid
        and period_start <= p["created_at"] < period_end
    ]
    policies.sort(key=lambda p: (p["created_at"], p["id"]))
    line_items = []
    total_written = 0
    total_commission = 0
    # PRD §3.6: "A cumulative tier cursor tracks the agent's written premium
    # already consumed across the statement period." — a single agent-scoped
    # cursor, not per-LOB. The schedule applied per policy is the agent's ACTIVE
    # schedule for that policy product's LOB whose window covers the policy's
    # created_at.
    tier_cursor = 0
    for p in policies:
        product = DB.products.get(p["product_id"])
        if product is None:
            continue
        lob = product["line_of_business"]
        schedule = find_covering_schedule(aid, lob, p["created_at"])
        if schedule is None:
            continue  # excluded entirely, not zero-rated
        remaining = p["written_premium_cents"]
        commission = Decimal(0)
        for tier in schedule["tiers"]:
            up_to = tier["up_to_cents"]
            rate = Decimal(str(tier["rate_pct"]))
            if up_to is None:
                capacity = remaining
            else:
                capacity = up_to - tier_cursor
            if capacity < 0:
                capacity = 0
            slice_cents = min(remaining, capacity)
            if slice_cents < 0:
                slice_cents = 0
            commission += Decimal(slice_cents) * rate
            tier_cursor += slice_cents
            remaining -= slice_cents
            if remaining == 0:
                break
        per_policy = rhu(commission)
        p["per_policy_commission_cents"] = per_policy
        total_written += p["written_premium_cents"]
        total_commission += per_policy
        line_items.append({
            "policy_id": p["id"],
            "premium_cents": p["written_premium_cents"],
            "commission_cents": per_policy,
        })
    s = new_entity()
    s.update({
        "agent_id": aid,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "written_premium_cents": total_written,
        "commission_cents": total_commission,
        "clawback_cents": 0,
        "net_payable_cents": total_commission - 0,
        "line_items": line_items,
    })
    DB.statements[s["id"]] = s
    return success(ser_statement(s), 201)


@app.get("/agents/<aid>/commission-statements")
def list_agent_commission_statements(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    get_or_404(DB.agents, aid, "agent")
    items = [s for s in DB.statements.values() if s["agent_id"] == aid]
    f_status = request.args.get("status")
    if f_status:
        items = [s for s in items if s["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_statement(s) for s in page], 200, pagination=meta)


@app.get("/commission-statements/<sid>")
def get_commission_statement(sid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    s = get_or_404(DB.statements, sid, "statement")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, s["agent_id"])
    return success(ser_statement(s), 200)


@app.post("/commission-statements/<sid>/finalize")
def finalize_statement(sid):
    require_role("CarrierAdmin")
    s = get_or_404(DB.statements, sid, "statement")
    if s["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT statement can be finalized")
    s["status"] = "FINALIZED"
    touch(s)
    return success(ser_statement(s), 200)


@app.post("/commission-statements/<sid>/pay")
def pay_statement(sid):
    require_role("CarrierAdmin")
    s = get_or_404(DB.statements, sid, "statement")
    # State rule (priority 6) fires before the fiscal rule (priority 10).
    if s["status"] != "FINALIZED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a FINALIZED statement can be paid")
    if s["net_payable_cents"] <= 0:
        raise_err("ERR_NOTHING_TO_PAY", "Cannot pay a statement with net_payable_cents == 0")
    s["status"] = "PAID"
    touch(s)
    return success(ser_statement(s), 200)


@app.post("/commission-statements/<sid>/claw-back")
def claw_back_statement(sid):
    require_role("CarrierAdmin")
    s = get_or_404(DB.statements, sid, "statement")
    body = get_body(required=True)
    policy_id = req_str(body, "policy_id")
    if s["status"] != "PAID":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a PAID statement can be clawed back")
    policy = get_or_404(DB.policies, policy_id, "policy")
    line = next((li for li in s["line_items"] if li["policy_id"] == policy_id), None)
    if line is None:
        raise_err("ERR_INVALID_REQUEST", "policy_id must appear in line_items")
    if policy["status"] != "CANCELLED":
        raise_err("ERR_POLICY_NOT_IN_FORCE", "Referenced policy must be CANCELLED")
    if policy["clawback_cents"] > 0:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Policy already carries a positive clawback_cents")
    per_policy = policy["per_policy_commission_cents"] or 0
    days = days_between(policy["inception_at"], policy["cancelled_at"])
    earned_portion = rhu(Decimal(per_policy) * days / policy["term_days"])
    clawback = per_policy - earned_portion
    new_net = s["commission_cents"] - (s["clawback_cents"] + clawback)
    if new_net < 0:
        raise_err("ERR_NEGATIVE_COMMISSION",
                  "Claw-back would drive statement net_payable_cents below zero")
    policy["clawback_cents"] = clawback
    touch(policy)
    s["clawback_cents"] += clawback
    s["net_payable_cents"] = s["commission_cents"] - s["clawback_cents"]
    s["status"] = "CLAWED_BACK"
    touch(s)
    return success(ser_statement(s), 200)


# ---- Contingent Bonus Pools / Payouts --------------------------------------

@app.post("/contingent-bonus-pools")
def create_pool():
    require_role("CarrierAdmin")
    body = get_body(required=True)
    year = req_int(body, "year")
    pool_total_cents = req_int(body, "pool_total_cents", minimum=0)
    loss_ratio_threshold = opt_num(body, "loss_ratio_threshold", 0.70)
    growth_threshold_pct = opt_num(body, "growth_threshold_pct", 0.05)
    p = new_entity()
    p.update({
        "year": year,
        "pool_total_cents": pool_total_cents,
        "loss_ratio_threshold": loss_ratio_threshold,
        "growth_threshold_pct": growth_threshold_pct,
        "status": "OPEN",
        "settled_at": None,
        "undistributed_cents": None,
    })
    DB.pools[p["id"]] = p
    return success(ser_pool(p), 201)


@app.get("/contingent-bonus-pools")
def list_pools():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    items = list(DB.pools.values())
    f_year = request.args.get("year")
    f_status = request.args.get("status")
    if f_year:
        try:
            fy = int(f_year)
        except ValueError:
            fy = None
        items = [p for p in items if p["year"] == fy]
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_pool(p) for p in page], 200, pagination=meta)


@app.get("/contingent-bonus-pools/<pid>")
def get_pool(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    p = get_or_404(DB.pools, pid, "pool")
    return success(ser_pool(p), 200)


@app.post("/contingent-bonus-pools/<pid>/settle")
def settle_pool(pid):
    require_role("CarrierAdmin")
    pool = get_or_404(DB.pools, pid, "pool")
    if pool["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only an OPEN pool can be settled")
    as_of = now()
    # STEP 1-2: eligibility gates first, excluding any bonus accrual.
    # Candidate agents: hold a contingent_bonus_eligible ACTIVE schedule AND
    # have positive trailing-12m earned premium.
    eligible_agents = []
    candidate_agents = set()
    for s in DB.schedules.values():
        if s["status"] == "ACTIVE" and s["contingent_bonus_eligible"]:
            candidate_agents.add(s["agent_id"])
    agent_evals = []
    for agent_id in candidate_agents:
        earned, _incurred = trailing_earned_and_incurred(agent_id, as_of)
        ratio, _e = trailing_loss_ratio(agent_id, as_of)
        # growth: prior 12m earned
        prior_start = as_of - timedelta(days=730)
        prior_end = as_of - timedelta(days=365)
        prior_earned = 0
        for p in DB.policies.values():
            if p["agent_id"] != agent_id:
                continue
            if prior_start <= p["inception_at"] <= prior_end:
                prior_earned += earned_in_window(p, prior_start, prior_end)
        if prior_earned == 0:
            growth = Decimal("1.0")
        else:
            growth = (Decimal(earned) - Decimal(prior_earned)) / Decimal(prior_earned)
        gate_loss = ratio < pool["loss_ratio_threshold"]
        gate_growth = growth >= Decimal(str(pool["growth_threshold_pct"]))
        eligible = gate_loss and gate_growth and earned > 0
        if not gate_loss:
            reason = "LOSS_RATIO"
        elif not gate_growth:
            reason = "GROWTH"
        else:
            reason = "NONE"
        agent_evals.append({
            "agent_id": agent_id,
            "earned": earned,
            "eligible": eligible,
            "ineligibility_reason": reason,
        })
    # Only agents with positive trailing earned enter the payout set at all.
    payout_targets = [e for e in agent_evals if e["earned"] > 0]
    eligible_pool = [e for e in payout_targets if e["eligible"]]
    total_eligible_earned = sum(e["earned"] for e in eligible_pool)
    for e in payout_targets:
        if e["eligible"] and total_eligible_earned > 0:
            payout = (Decimal(pool["pool_total_cents"]) * e["earned"]
                      / total_eligible_earned)
            payout_cents = int(payout.to_integral_value(rounding="ROUND_FLOOR"))
        else:
            payout_cents = 0
        pay = new_entity()
        pay.update({
            "pool_id": pool["id"],
            "agent_id": e["agent_id"],
            "earned_premium_cents": e["earned"],
            "eligible": e["eligible"],
            "ineligibility_reason": e["ineligibility_reason"] if not e["eligible"] else "NONE",
            "payout_cents": payout_cents,
        })
        DB.payouts[pay["id"]] = pay
    distributed = sum(DB.payouts[p]["payout_cents"] for p in DB.payouts
                      if DB.payouts[p]["pool_id"] == pool["id"])
    pool["undistributed_cents"] = pool["pool_total_cents"] - distributed
    pool["status"] = "SETTLED"
    pool["settled_at"] = now()
    touch(pool)
    return success(ser_pool(pool), 200)


@app.get("/contingent-bonus-pools/<pid>/bonus-payouts")
def list_pool_payouts(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    get_or_404(DB.pools, pid, "pool")
    items = [p for p in DB.payouts.values() if p["pool_id"] == pid]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_payout(p) for p in page], 200, pagination=meta)


@app.get("/agents/<aid>/bonus-payouts")
def list_agent_payouts(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    get_or_404(DB.agents, aid, "agent")
    items = [p for p in DB.payouts.values() if p["agent_id"] == aid]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_payout(p) for p in page], 200, pagination=meta)


@app.get("/bonus-payouts/<pid>")
def get_payout(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    p = get_or_404(DB.payouts, pid, "payout")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, p["agent_id"])
    return success(ser_payout(p), 200)


# ---- Portfolio Reviews ------------------------------------------------------

@app.post("/agents/<aid>/portfolio-reviews")
def create_portfolio_review(aid):
    user_id, _role = require_role("UnderwritingReviewer")
    get_or_404(DB.agents, aid, "agent")
    body = get_body(required=True)
    reason = req_str(body, "reason")
    for r in DB.reviews.values():
        if r["agent_id"] == aid and r["status"] == "OPEN":
            raise_err("ERR_REVIEW_ALREADY_OPEN",
                      "An OPEN review already exists for this agent")
    ratio, earned = trailing_loss_ratio(aid, now())
    r = new_entity()
    r.update({
        "agent_id": aid,
        "reason": reason,
        "opened_by_user_id": user_id,
        "status": "OPEN",
        "trailing_loss_ratio": ratio,
        "earned_premium_trailing_cents": earned,
        "findings": None,
        "action": None,
        "actioned_by_user_id": None,
    })
    DB.reviews[r["id"]] = r
    return success(ser_review(r), 201)


@app.get("/agents/<aid>/portfolio-reviews")
def list_agent_reviews(aid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    get_or_404(DB.agents, aid, "agent")
    items = [r for r in DB.reviews.values() if r["agent_id"] == aid]
    f_status = request.args.get("status")
    if f_status:
        items = [r for r in items if r["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_review(r) for r in page], 200, pagination=meta)


@app.get("/portfolio-reviews/<rid>")
def get_review(rid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    r = get_or_404(DB.reviews, rid, "review")
    user_id, role = get_auth()
    if role == "Agent":
        check_ownership(user_id, role, r["agent_id"])
    return success(ser_review(r), 200)


@app.post("/portfolio-reviews/<rid>/issue-findings")
def issue_findings(rid):
    require_role("UnderwritingReviewer")
    r = get_or_404(DB.reviews, rid, "review")
    body = get_body(required=True)
    findings = req_str(body, "findings")
    if r["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an OPEN review can have findings issued")
    r["findings"] = findings
    r["status"] = "FINDINGS_ISSUED"
    touch(r)
    return success(ser_review(r), 200)


@app.post("/portfolio-reviews/<rid>/take-action")
def take_review_action(rid):
    user_id, _role = require_role("UnderwritingReviewer")
    r = get_or_404(DB.reviews, rid, "review")
    body = get_body(required=True)
    action = req_enum(body, "action", {"CONTINUE", "SUSPEND", "TERMINATE"})
    if r["status"] != "FINDINGS_ISSUED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a FINDINGS_ISSUED review can be actioned")
    if user_id == r["opened_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "Actioning reviewer's X-User-ID must differ from opened_by_user_id")
    agent = get_or_404(DB.agents, r["agent_id"], "agent")
    if action == "TERMINATE":
        for pl in DB.placements.values():
            if pl["agent_id"] == agent["id"] and pl["status"] == "PLACED":
                raise_err("ERR_AGENT_HAS_ACTIVE_PLACEMENTS",
                          "Agent holds PLACED bundle placements")
    r["action"] = action
    r["actioned_by_user_id"] = user_id
    r["status"] = "ACTION_TAKEN"
    touch(r)
    if action == "SUSPEND" and agent["status"] == "APPOINTED":
        agent["status"] = "SUSPENDED"
        touch(agent)
    elif action == "TERMINATE":
        _terminate_agent(agent, reason=None)
    return success(ser_review(r), 200)


# ---- Bundle Placements ------------------------------------------------------

@app.post("/policies/<pid>/bundle-placements")
def create_bundle_placement(pid):
    user_id, role = require_role("Agent", "CarrierAdmin")
    policy = get_or_404(DB.policies, pid, "policy")
    body = get_body(required=True)
    unaffiliated_carrier_name = req_str(body, "unaffiliated_carrier_name")
    home_premium_cents = req_int(body, "home_premium_cents", minimum=0)
    total_commission_cents = req_int(body, "total_commission_cents", minimum=0)
    product = get_or_404(DB.products, policy["product_id"], "product")
    if role == "Agent":
        # The acting agent must be the policy's agent of record.
        check_ownership(user_id, role, policy["agent_id"])
    if policy["status"] != "IN_FORCE":
        raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
    if not product["bundle_eligible"]:
        raise_err("ERR_BUNDLE_NOT_ELIGIBLE",
                  "Bundle placements require a bundle_eligible product")
    if policy["agent_id"] is None:
        raise_err("ERR_AGENT_MISMATCH",
                  "Direct policy with no agent cannot take a bundle placement")
    p = new_entity()
    p.update({
        "policy_id": pid,
        "agent_id": policy["agent_id"],
        "unaffiliated_carrier_name": unaffiliated_carrier_name,
        "home_premium_cents": home_premium_cents,
        "total_commission_cents": total_commission_cents,
        "status": "QUOTED",
        "transferred_to_agent_id": None,
        "earned_commission_cents": None,
        "transferred_commission_cents": None,
    })
    DB.placements[p["id"]] = p
    return success(ser_placement(p), 201)


@app.get("/policies/<pid>/bundle-placements")
def list_policy_placements(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    get_or_404(DB.policies, pid, "policy")
    items = [p for p in DB.placements.values() if p["policy_id"] == pid]
    f_status = request.args.get("status")
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_placement(p) for p in page], 200, pagination=meta)


@app.get("/bundle-placements")
def list_placements():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent", "System")
    items = list(DB.placements.values())
    f_agent = request.args.get("agent_id")
    f_transferred = request.args.get("transferred_to_agent_id")
    f_status = request.args.get("status")
    if f_agent:
        items = [p for p in items if p["agent_id"] == f_agent]
    if f_transferred:
        items = [p for p in items if p["transferred_to_agent_id"] == f_transferred]
    if f_status:
        items = [p for p in items if p["status"] == f_status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success([ser_placement(p) for p in page], 200, pagination=meta)


@app.get("/bundle-placements/<pid>")
def get_placement(pid):
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "Agent",
                 "Consumer", "ComparativeRater", "System")
    p = get_or_404(DB.placements, pid, "placement")
    return success(ser_placement(p), 200)


@app.post("/bundle-placements/<pid>/place")
def place_bundle_placement(pid):
    user_id, role = require_role("Agent")
    p = get_or_404(DB.placements, pid, "placement")
    check_ownership(user_id, role, p["agent_id"])
    if p["status"] != "QUOTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only a QUOTED placement can be placed")
    policy = get_or_404(DB.policies, p["policy_id"], "policy")
    if policy["status"] != "IN_FORCE":
        raise_err("ERR_POLICY_NOT_IN_FORCE", "Policy must be IN_FORCE")
    p["status"] = "PLACED"
    touch(p)
    return success(ser_placement(p), 200)


@app.post("/bundle-placements/<pid>/transfer-aor")
def transfer_aor(pid):
    require_role("CarrierAdmin")
    p = get_or_404(DB.placements, pid, "placement")
    body = get_body(required=True)
    new_agent_id = req_str(body, "new_agent_id")
    if p["status"] != "PLACED":
        raise_err("ERR_AOR_NOT_ALLOWED",
                  "transfer-aor applies only to a PLACED placement")
    if new_agent_id == p["agent_id"]:
        raise_err("ERR_AOR_NOT_ALLOWED",
                  "new_agent_id must differ from the current agent_id")
    new_agent = get_or_404(DB.agents, new_agent_id, "agent")
    if new_agent["status"] != "APPOINTED":
        raise_err("ERR_AOR_NOT_ALLOWED", "New agent must be APPOINTED")
    policy = get_or_404(DB.policies, p["policy_id"], "policy")
    product = get_or_404(DB.products, policy["product_id"], "product")
    if not has_active_appointment(new_agent_id, product["state_code"], product["line_of_business"]):
        raise_err("ERR_AGENT_NOT_APPOINTED_IN_STATE",
                  "New agent must hold an ACTIVE appointment for (state, line)")
    days = days_between(policy["inception_at"], now())
    earned = rhu(Decimal(p["total_commission_cents"]) * days / policy["term_days"])
    transferred = p["total_commission_cents"] - earned
    p["earned_commission_cents"] = earned
    p["transferred_commission_cents"] = transferred
    p["agent_id"] = new_agent_id
    p["transferred_to_agent_id"] = new_agent_id
    p["status"] = "AOR_TRANSFERRED"
    touch(p)
    return success(ser_placement(p), 200)


@app.post("/bundle-placements/<pid>/decline")
def decline_placement(pid):
    user_id, role = require_role("Agent", "CarrierAdmin")
    p = get_or_404(DB.placements, pid, "placement")
    if p["status"] == "QUOTED":
        # Agent must own the placement; CarrierAdmin may decline any QUOTED placement.
        if role == "Agent":
            check_ownership(user_id, role, p["agent_id"])
    elif p["status"] == "PLACED":
        # PRD §3.9: declining a PLACED placement is reserved to CarrierAdmin. The
        # PLACED -> DECLINED transition is not defined for the Agent actor.
        if role != "CarrierAdmin":
            raise_err("ERR_INVALID_STATE_TRANSITION",
                      "Declining a PLACED placement is reserved to CarrierAdmin")
    else:
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  f"Cannot decline a placement in {p['status']}")
    p["status"] = "DECLINED"
    touch(p)
    return success(ser_placement(p), 200)


# ---- Leakage Analytics ------------------------------------------------------

@app.get("/leakage-reports/quote-to-bind")
def leakage_report():
    require_role("CarrierAdmin", "RatingManager", "UnderwritingReviewer", "System")
    args = request.args
    period_start_raw = args.get("period_start")
    period_end_raw = args.get("period_end")
    basis = args.get("basis")
    channel_filter = args.get("channel")
    if not period_start_raw or not period_end_raw or not basis:
        raise_err("ERR_INVALID_REQUEST",
                  "period_start, period_end, and basis are required query params")
    if basis not in ("COUNT", "PREMIUM_WEIGHTED"):
        raise_err("ERR_INVALID_REQUEST", "basis must be COUNT or PREMIUM_WEIGHTED")
    period_start = parse_dt(period_start_raw)
    period_end = parse_dt(period_end_raw)
    if period_end <= period_start:
        raise_err("ERR_INVALID_REQUEST", "period_end must be after period_start")
    channels = ["DIRECT", "AGENT"] if channel_filter is None else [channel_filter]
    if channel_filter is not None and channel_filter not in ("DIRECT", "AGENT"):
        raise_err("ERR_INVALID_REQUEST", "channel must be DIRECT or AGENT")
    out_channels = []
    for ch in channels:
        cohort = [
            q for q in DB.quotes.values()
            if q["channel"] == ch
            and q["quoted_at"] is not None
            and period_start <= q["quoted_at"] < period_end
        ]
        # leaked = did NOT reach BOUND with bind < period_end. The quote record
        # tracks only its current status; "BOUND" means it is bound (its policy
        # was created at bind time, which is the bind instant).
        leaked = []
        for q in cohort:
            if q["status"] == "BOUND":
                policy = next(
                    (p for p in DB.policies.values() if p["quote_id"] == q["id"]),
                    None,
                )
                # bind time == policy.created_at
                if policy is not None and policy["created_at"] < period_end:
                    continue  # not leaked
            leaked.append(q)
        if basis == "COUNT":
            cohort_n = len(cohort)
            leaked_n = len(leaked)
            if cohort_n == 0:
                leakage = 0.0
            else:
                leakage = round4(Decimal(leaked_n) / Decimal(cohort_n))
            entry = {
                "channel": ch,
                "cohort_count": cohort_n,
                "leaked_count": leaked_n,
                "leakage": leakage,
            }
        else:  # PREMIUM_WEIGHTED
            total_premium = sum(q["quoted_premium_cents"] or 0 for q in cohort)
            leaked_premium = sum(q["quoted_premium_cents"] or 0 for q in leaked)
            if total_premium == 0:
                leakage = 0.0
            else:
                leakage = round4(Decimal(leaked_premium) / Decimal(total_premium))
            entry = {
                "channel": ch,
                "cohort_count": len(cohort),
                "leaked_count": len(leaked),
                "cohort_premium_cents": total_premium,
                "leaked_premium_cents": leaked_premium,
                "leakage": leakage,
            }
        out_channels.append(entry)
    report = {
        "basis": basis,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "channels": out_channels,
    }
    return success(report, 200)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # threaded=True: under the 8-round parallel sweep, a keep-alive probe or
    # slow-close connection on the single-threaded Werkzeug server would block
    # subsequent requests on a fresh socket ("Connection reset by peer").
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
