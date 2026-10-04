"""Shared helpers: body validation, datetime parsing, money rounding, lookups."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask import request

import db
from errors import err


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def body_json():
    if not request.is_json:
        # Treat empty body on POST with no required input as {}.
        if request.content_length in (None, 0):
            return {}
        raise err("ERR_INVALID_REQUEST", "Request body must be JSON.")
    data = request.get_json(silent=True)
    if data is None:
        if request.content_length in (None, 0):
            return {}
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}.")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise err("ERR_INVALID_REQUEST", f"{field} must be a non-empty string.")
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}.")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}.")
    return v


def round_half_up_cents(value):
    """value is a Decimal or numeric; return int of whole cents, ROUND_HALF_UP."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_or_404(store, entity_id, label="Resource"):
    obj = store.get(entity_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", f"{label} not found.")
    return obj


def stamp_new(entity, with_version=True):
    now = db.now_iso()
    entity["id"] = db.new_id()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Bump updated_at and version by exactly 1."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def paginate(items):
    """Apply limit/offset query params; return (page, limit, offset, total, has_more)."""
    from flask import request as _req
    try:
        limit = int(_req.args.get("limit", 10))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = int(_req.args.get("offset", 0))
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, limit, offset, total, has_more


def sort_by_created_at(items):
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


# ---------- domain helpers ----------

def branch_active_administrator(branch_id):
    for a in db.administrators.values():
        if a.get("branch_id") == branch_id and a.get("status") == "ACTIVE":
            return a
    return None


def branch_advisor(branch_id):
    """The advisor assigned to the branch (status not RETIRED/TERMINATED)."""
    for adv in db.advisors.values():
        if adv.get("branch_id") == branch_id and adv.get("status") not in ("RETIRED", "TERMINATED"):
            return adv
    return None


def recompute_staffing(branch):
    """Recompute branch.staffing_status from advisor + BOA presence."""
    adv = branch_advisor(branch["id"])
    adm = branch_active_administrator(branch["id"])
    if adv is not None and adv.get("status") == "RETIRING":
        branch["staffing_status"] = "SUCCESSION_PENDING"
    elif adv is not None and adm is not None:
        branch["staffing_status"] = "FULLY_STAFFED"
    elif adv is not None:
        branch["staffing_status"] = "ADVISOR_ASSIGNED"
    else:
        branch["staffing_status"] = "UNSTAFFED"


def recompute_tier(branch):
    """Service tier per §3.6: score = hh*10 + aum//100000; <300 TIER_1, <=900 TIER_2, else TIER_3."""
    score = branch.get("household_count", 0) * 10 + (branch.get("assets_under_care_dollars", 0) // 100000)
    branch["tier_score"] = score
    if score < 300:
        branch["service_tier"] = "TIER_1"
    elif score <= 900:
        branch["service_tier"] = "TIER_2"
    else:
        branch["service_tier"] = "TIER_3"


def profit_share(net_cents):
    """Tiered advisor profit share; per-tier round-half-up then sum (§3.6)."""
    if net_cents <= 0:
        return 0
    t1 = min(net_cents, 500000)
    t2 = min(max(net_cents - 500000, 0), 500000)
    t3 = max(net_cents - 1000000, 0)
    share = (round_half_up_cents(Decimal(t1) * Decimal("0.38"))
             + round_half_up_cents(Decimal(t2) * Decimal("0.42"))
             + round_half_up_cents(Decimal(t3) * Decimal("0.46")))
    return share


def period_gross_revenue(period):
    """Sum of POSTED production commissions for the branch's advisor(s) in [start, end)."""
    branch_id = period["branch_id"]
    start = parse_dt(period["period_start"], "period_start")
    end = parse_dt(period["period_end"], "period_end")
    total = 0
    for rec in db.production_records.values():
        if rec.get("status") != "POSTED":
            continue
        adv = db.advisors.get(rec.get("advisor_id"))
        if adv is None:
            continue
        # Revenue lines belong to the branch via the branch's advisor.
        if adv.get("branch_id") != branch_id:
            continue
        posted = parse_dt(rec["posted_at"], "posted_at")
        if start <= posted < end:
            total += rec.get("commissions_cents", 0)
    return total


def period_total_charges(period):
    total = 0
    for ch in db.charges.values():
        if ch.get("period_id") == period["id"] and ch.get("status") == "POSTED":
            total += ch.get("amount_cents", 0)
    return total


def recompute_period(period):
    """Recompute aggregates (provisional variant)."""
    gross = period_gross_revenue(period)
    charges_total = period_total_charges(period)
    net = gross - charges_total
    period["gross_revenue_cents"] = gross
    period["total_charges_cents"] = charges_total
    period["net_profit_cents"] = net
    period["advisor_share_cents"] = profit_share(net)


def recompute_advisor_cumulative(advisor):
    """Sum of commissions_cents across advisor's POSTED production records since hire_date."""
    hire = parse_dt(advisor["hire_date"], "hire_date")
    total = 0
    for rec in db.production_records.values():
        if rec.get("advisor_id") != advisor["id"]:
            continue
        if rec.get("status") != "POSTED":
            continue
        posted = parse_dt(rec["posted_at"], "posted_at")
        if posted >= hire:
            total += rec.get("commissions_cents", 0)
    advisor["cumulative_commissions_cents"] = total


def active_transfer_for_branch(branch_id):
    """A transfer in OFFERED/NEGOTIATING/ACCEPTED on the branch, or None."""
    for t in db.goodwill_transfers.values():
        if t.get("branch_id") == branch_id and t.get("status") in ("OFFERED", "NEGOTIATING", "ACCEPTED"):
            return t
    return None


def release_territory(territory):
    """Release a territory assignment back to OPEN (ASSIGNED -> OPEN system transition)."""
    territory["assigned_advisor_id"] = None
    territory["assignment_end"] = db.now_iso()
    territory["status"] = "OPEN"
    touch(territory)
