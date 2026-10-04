"""Drive-Thru Coffee Stand API — Flask implementation.

Single-process in-memory implementation of the PRD in workspace/PRD.md.
The store starts empty on every boot; the logical clock starts at
2026-09-01T00:00:00Z (PRD §2.4).
"""
import os
import re
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error catalog (PRD §5)
# ---------------------------------------------------------------------------

HTTP_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_INVALID_PAYLOAD": 400,
    "ERR_REGION_NOT_FOUND": 404,
    "ERR_STAND_NOT_FOUND": 404,
    "ERR_CREW_MEMBER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_RECIPE_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_LOYALTY_ACCOUNT_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_ITEM_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_STAND_INVALID_TRANSITION": 409,
    "ERR_STAND_NOT_ACCEPTING_ORDERS": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_SHIFT_INVALID_STATE": 409,
    "ERR_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_PAYMENT_INVALID_STATE": 409,
    "ERR_DISTRIBUTION_INVALID_STATE": 409,
    "ERR_WINDOW_INVALID_STATE": 409,
    "ERR_CERTIFICATION_EXPIRED": 422,
    "ERR_SHIFT_IN_PAST": 422,
    "ERR_ASSIGNMENT_OVERLAP": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_RECIPE_OUT_OF_SEASON": 422,
    "ERR_WINDOW_NOT_CLOSABLE": 409,
    "ERR_EMPTY_ORDER": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_MODIFIER_UNKNOWN": 422,
    "ERR_ROTATION_STRETCH_EXCEEDED": 422,
    "ERR_ASSIGNMENT_OUTSIDE_SHIFT": 422,
    "ERR_PEAK_STAFFING_INSUFFICIENT": 422,
    "ERR_LANE_STACKING_FULL": 409,
    "ERR_CAPTURE_OUT_OF_SEQUENCE": 409,
    "ERR_SITE_STACKING_INSUFFICIENT": 422,
    "ERR_INGRESS_GAP_INSUFFICIENT": 422,
    "ERR_TENURE_INSUFFICIENT": 422,
    "ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS": 409,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_DISTRIBUTION_NOT_ACTIVE": 409,
    "ERR_SECRET_MENU_TIER_REQUIRED": 403,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_NO_ACTIVE_AGREEMENT_FOR_STAND": 409,
    "ERR_PAYMENT_DECLINED": 402,
    "ERR_REFUND_EXCEEDS_CAPTURED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = HTTP_STATUS[error_id]
        super().__init__(self.message)


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Envelope helpers (PRD §2.2)
# ---------------------------------------------------------------------------

_req_counter = [0]


def _request_id():
    _req_counter[0] += 1
    return f"req_{uuid.uuid4().hex[:20]}{_req_counter[0]:06d}"


def _now_ts():
    """ISO 8601 UTC timestamp with three fractional digits (real clock, for
    created_at/updated_at and api_request_timestamp)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status=200, pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _now_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _now_ts()},
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _now_ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "unknown route"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _now_ts()},
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "method not allowed"},
    }
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# In-memory store (PRD §2.4: starts empty every boot)
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.regions = {}
        self.stands = {}
        self.crew_members = {}
        self.agreements = {}
        self.recipes = {}
        self.distributions = {}
        self.loyalty_accounts = {}
        self.shifts = {}
        self.assignments = {}
        self.orders = {}
        self.order_items = {}
        self.payments = {}
        self.windows = {}
        # Per-stand, per-lane monotonic lane_seq counters (never reused).
        self.lane_seq = {}  # stand_id -> {lane_code: last_seq}
        # Logical clock (PRD §2.4): fixed startup default, never wall-clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


DB = Store()


def new_id():
    return str(uuid.uuid4())


def touch(rec, created=False):
    now = _now_ts()
    if created:
        rec["id"] = new_id()
        rec["created_at"] = now
        rec["updated_at"] = now
        rec["version"] = 1
    else:
        rec["updated_at"] = now
        rec["version"] += 1
    return rec


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        err("ERR_INVALID_PAYLOAD", f"{field} must be an ISO 8601 string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        err("ERR_INVALID_PAYLOAD", f"{field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        err("ERR_INVALID_PAYLOAD", f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        err("ERR_INVALID_PAYLOAD", f"{field} is not a valid ISO date")


def clock_iso():
    """Logical clock as the canonical 'YYYY-MM-DDTHH:MM:SSZ' string."""
    return DB.clock.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_date():
    return DB.clock.date()


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------

VALID_ROLES = {
    "PlatformAdmin", "RegionalManager", "StandOperator",
    "ShiftLead", "CrewMember", "LoyaltyCustomer",
}


def auth(allowed_roles):
    """Priority 1-2: header presence/non-emptiness, then role admission."""
    user_id = request.headers.get("X-User-ID") or ""
    role = request.headers.get("X-User-Role") or ""
    if not user_id.strip() or not role.strip():
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in VALID_ROLES or role not in allowed_roles:
        err("ERR_UNAUTHORIZED_ROLE",
            f"role {role!r} is not permitted for this operation")
    return user_id, role


def get_json():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        err("ERR_INVALID_PAYLOAD", "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Input coercion helpers (payload shape — priority 4)
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        err("ERR_INVALID_PAYLOAD", f"{field} is required and must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_PAYLOAD", f"{field} is required and must be an integer")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        err("ERR_INVALID_PAYLOAD", f"{field} is required and must be a boolean")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_PAYLOAD", f"{field} is required and must be a number")
    return v


def forbid_extra(body, allowed):
    extra = [k for k in body.keys() if k not in allowed]
    if extra:
        err("ERR_INVALID_PAYLOAD", f"unexpected field(s): {', '.join(sorted(extra))}")


# ---------------------------------------------------------------------------
# Entity lookups (existence — priority 3)
# ---------------------------------------------------------------------------

def get_region(rid):
    r = DB.regions.get(rid)
    if r is None:
        err("ERR_REGION_NOT_FOUND", f"region {rid} not found")
    return r


def get_stand(sid):
    s = DB.stands.get(sid)
    if s is None:
        err("ERR_STAND_NOT_FOUND", f"stand {sid} not found")
    return s


def get_crew(cid):
    c = DB.crew_members.get(cid)
    if c is None:
        err("ERR_CREW_MEMBER_NOT_FOUND", f"crew member {cid} not found")
    return c


def get_agreement(aid):
    a = DB.agreements.get(aid)
    if a is None:
        err("ERR_AGREEMENT_NOT_FOUND", f"agreement {aid} not found")
    return a


def get_recipe(rid):
    r = DB.recipes.get(rid)
    if r is None:
        err("ERR_RECIPE_NOT_FOUND", f"recipe {rid} not found")
    return r


def get_distribution(did):
    d = DB.distributions.get(did)
    if d is None:
        err("ERR_DISTRIBUTION_NOT_FOUND", f"distribution {did} not found")
    return d


def get_account(aid):
    a = DB.loyalty_accounts.get(aid)
    if a is None:
        err("ERR_LOYALTY_ACCOUNT_NOT_FOUND", f"loyalty account {aid} not found")
    return a


def get_shift(sid):
    s = DB.shifts.get(sid)
    if s is None:
        err("ERR_SHIFT_NOT_FOUND", f"shift {sid} not found")
    return s


def get_assignment(aid):
    a = DB.assignments.get(aid)
    if a is None:
        err("ERR_ASSIGNMENT_NOT_FOUND", f"assignment {aid} not found")
    return a


def get_order(oid):
    o = DB.orders.get(oid)
    if o is None:
        err("ERR_ORDER_NOT_FOUND", f"order {oid} not found")
    return o


def get_item(iid):
    i = DB.order_items.get(iid)
    if i is None:
        err("ERR_ORDER_ITEM_NOT_FOUND", f"order item {iid} not found")
    return i


def get_payment(pid):
    p = DB.payments.get(pid)
    if p is None:
        err("ERR_PAYMENT_NOT_FOUND", f"payment {pid} not found")
    return p


def get_window(wid):
    w = DB.windows.get(wid)
    if w is None:
        err("ERR_WINDOW_NOT_FOUND", f"throughput window {wid} not found")
    return w


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(records):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    records = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Loyalty helpers (PRD §3.4)
# ---------------------------------------------------------------------------

def compute_tier(points):
    if points >= 500:
        return "GOLD"
    if points >= 200:
        return "SILVER"
    return "NONE"


def tier_pct(tier):
    if tier == "GOLD":
        return Decimal("0.10")
    if tier == "SILVER":
        return Decimal("0.05")
    return Decimal("0")


def apply_points(account, delta):
    account["points"] = max(0, account["points"] + delta)
    account["tier"] = compute_tier(account["points"])
    touch(account)


def round_half_up_cents(value_decimal):
    return int(value_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lane helpers (PRD §3.6)
# ---------------------------------------------------------------------------

def lane_config(stand, lane_code):
    for lc in stand["lane_configs"]:
        if lc["lane_code"] == lane_code:
            return lc
    return None


def lane_occupancy(stand, lane_code):
    """Count of orders in the lane with queue_status MERGED or AT_WINDOW."""
    count = 0
    for o in DB.orders.values():
        if (o["stand_id"] == stand["id"] and o.get("lane_code") == lane_code
                and o["queue_status"] in ("MERGED", "AT_WINDOW")):
            count += 1
    return count


def recompute_lane_occupancy(stand):
    occ = {}
    for o in DB.orders.values():
        if (o["stand_id"] == stand["id"] and o.get("lane_code")
                and o["queue_status"] in ("MERGED", "AT_WINDOW")):
            occ[o["lane_code"]] = occ.get(o["lane_code"], 0) + 1
    stand["lane_occupancy"] = occ


def next_lane_seq(stand_id, lane_code):
    lanes = DB.lane_seq.setdefault(stand_id, {})
    nxt = lanes.get(lane_code, 0) + 1
    lanes[lane_code] = nxt
    return nxt


def select_lane(stand):
    """lane_merge_position selector (PRD §3.6)."""
    candidates = []
    for lc in stand["lane_configs"]:
        code = lc["lane_code"]
        occupied = lane_occupancy(stand, code)
        if occupied >= lc["max_stack_cars"]:
            continue  # no free stacking slot
        projected = 0
        for o in DB.orders.values():
            if (o["stand_id"] == stand["id"] and o.get("lane_code") == code
                    and o["queue_status"] in ("MERGED", "AT_WINDOW")):
                projected += o["outstanding_build_seconds"]
        candidates.append((projected, occupied, code))
    if not candidates:
        err("ERR_LANE_STACKING_FULL", "no lane has a free stacking slot")
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Order totals recompute (PRD §3.6)
# ---------------------------------------------------------------------------

def order_items_of(order_id):
    return [i for i in DB.order_items.values() if i["order_id"] == order_id]


def recompute_order_totals(order):
    items = [i for i in order_items_of(order["id"]) if i["build_status"] != "CANCELLED"]
    order["subtotal_cents"] = sum(i["line_gross_cents"] for i in items)
    order["discount_cents"] = sum(i["line_discount_cents"] for i in items)
    order["total_cents"] = order["subtotal_cents"] - order["discount_cents"]
    order["outstanding_build_seconds"] = sum(
        i["build_time_seconds"] for i in items
        if i["build_status"] in ("PENDING", "BUILDING")
    )


def cancel_open_items(order):
    for item in order_items_of(order["id"]):
        if item["build_status"] in ("PENDING", "BUILDING"):
            item["build_status"] = "CANCELLED"
            touch(item)
    recompute_order_totals(order)


def payment_of_order(order_id):
    for p in DB.payments.values():
        if p["order_id"] == order_id:
            return p
    return None


def abandon_order_row(order):
    """PRD §3.8: abandonment side effects (queue already validated by caller)."""
    order["queue_status"] = "ABANDONED"
    if order["payment_status"] == "AUTHORIZED":
        pay = payment_of_order(order["id"])
        if pay is not None:
            pay["status"] = "VOIDED"
            touch(pay)
        order["payment_status"] = "VOIDED"
    cancel_open_items(order)
    touch(order)


def suspend_stand_cascade(stand):
    """PRD §3.2: stand OPEN|THROTTLED -> SUSPENDED with queue drain."""
    if stand["status"] not in ("OPEN", "THROTTLED"):
        return
    stand["status"] = "SUSPENDED"
    for o in DB.orders.values():
        if o["stand_id"] == stand["id"] and o["queue_status"] in (
                "QUEUED", "MERGED", "AT_WINDOW"):
            abandon_order_row(o)
    recompute_lane_occupancy(stand)
    touch(stand)


def active_agreement_for_stand(stand_id):
    for a in DB.agreements.values():
        if a["stand_id"] == stand_id and a["status"] == "ACTIVE":
            return a
    return None


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    auth({"PlatformAdmin"})
    body = get_json()
    to_iso8601 = req_str(body, "to_iso8601")
    DB.clock = parse_dt(to_iso8601, "to_iso8601")
    return success({"current_utc": clock_iso()}, 200)


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------

@app.post("/regions")
def create_region():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"name", "code"})
    name = req_str(body, "name")
    code = req_str(body, "code")
    rec = {"name": name, "code": code}
    touch(rec, created=True)
    DB.regions[rec["id"]] = rec
    return success(rec, 201)


@app.get("/regions/<region_id>")
def read_region(region_id):
    auth(VALID_ROLES)
    return success(get_region(region_id), 200)


# ---------------------------------------------------------------------------
# Stands (PRD §3.1)
# ---------------------------------------------------------------------------

def validate_lane_configs(value):
    if not isinstance(value, list) or not (1 <= len(value) <= 2):
        err("ERR_INVALID_PAYLOAD", "lane_configs must be an array of 1..2 entries")
    seen = set()
    out = []
    for entry in value:
        if not isinstance(entry, dict):
            err("ERR_INVALID_PAYLOAD", "each lane config must be an object")
        code = entry.get("lane_code")
        if not isinstance(code, str) or not code.strip():
            err("ERR_INVALID_PAYLOAD", "lane_code must be a non-empty string")
        cap = entry.get("max_stack_cars")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            err("ERR_INVALID_PAYLOAD", "max_stack_cars must be an integer >= 1")
        if code in seen:
            err("ERR_INVALID_PAYLOAD", "lane_code must be unique per stand")
        seen.add(code)
        out.append({"lane_code": code, "max_stack_cars": cap})
    return out


@app.post("/stands")
def create_stand():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"region_id", "name", "min_ingress_gap_seconds", "lane_configs"})
    region_id = body.get("region_id")
    if not isinstance(region_id, str):
        err("ERR_INVALID_PAYLOAD", "region_id is required")
    get_region(region_id)  # body FK existence (priority 3)
    name = req_str(body, "name")
    gap = req_int(body, "min_ingress_gap_seconds")
    lane_configs = validate_lane_configs(body.get("lane_configs"))
    rec = {
        "region_id": region_id,
        "name": name,
        "min_ingress_gap_seconds": gap,
        "lane_configs": lane_configs,
        "status": "PROPOSED",
        "consecutive_breach_windows": 0,
        "lane_occupancy": {},
    }
    touch(rec, created=True)
    DB.stands[rec["id"]] = rec
    DB.lane_seq[rec["id"]] = {}
    return success(rec, 201)


@app.get("/stands/<stand_id>")
def read_stand(stand_id):
    auth(VALID_ROLES)
    return success(get_stand(stand_id), 200)


@app.get("/stands")
def list_stands():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    region_id = request.args.get("region_id")
    status = request.args.get("status")
    rows = list(DB.stands.values())
    if region_id is not None:
        rows = [s for s in rows if s["region_id"] == region_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/stands/<stand_id>/approve")
def approve_stand(stand_id):
    auth({"PlatformAdmin"})
    stand = get_stand(stand_id)
    if stand["status"] != "PROPOSED":
        err("ERR_STAND_INVALID_TRANSITION", "only a PROPOSED stand can be approved")
    total_stack = sum(lc["max_stack_cars"] for lc in stand["lane_configs"])
    if total_stack < 10:
        err("ERR_SITE_STACKING_INSUFFICIENT",
            f"total lane stacking capacity {total_stack} < 10")
    if stand["min_ingress_gap_seconds"] < 30:
        err("ERR_INGRESS_GAP_INSUFFICIENT",
            f"min_ingress_gap_seconds {stand['min_ingress_gap_seconds']} < 30")
    stand["status"] = "APPROVED"
    touch(stand)
    return success(stand, 200)


@app.post("/stands/<stand_id>/open")
def open_stand(stand_id):
    auth({"StandOperator"})
    stand = get_stand(stand_id)
    if stand["status"] not in ("APPROVED", "SUSPENDED"):
        err("ERR_STAND_INVALID_TRANSITION",
            f"cannot open a stand in status {stand['status']}")
    if active_agreement_for_stand(stand_id) is None:
        err("ERR_NO_ACTIVE_AGREEMENT_FOR_STAND",
            "an ACTIVE operator agreement is required to open the stand")
    stand["status"] = "OPEN"
    stand["consecutive_breach_windows"] = 0
    touch(stand)
    return success(stand, 200)


@app.post("/stands/<stand_id>/throttle")
def throttle_stand(stand_id):
    auth({"ShiftLead"})
    stand = get_stand(stand_id)
    if stand["status"] != "OPEN":
        err("ERR_STAND_INVALID_TRANSITION", "only an OPEN stand can be throttled")
    stand["status"] = "THROTTLED"
    touch(stand)
    return success(stand, 200)


@app.post("/stands/<stand_id>/resume")
def resume_stand(stand_id):
    auth({"ShiftLead"})
    stand = get_stand(stand_id)
    if stand["status"] != "THROTTLED":
        err("ERR_STAND_INVALID_TRANSITION", "only a THROTTLED stand can be resumed")
    stand["status"] = "OPEN"
    touch(stand)
    return success(stand, 200)


@app.post("/stands/<stand_id>/close")
def close_stand(stand_id):
    auth({"StandOperator"})
    stand = get_stand(stand_id)
    if stand["status"] not in ("OPEN", "THROTTLED"):
        err("ERR_STAND_INVALID_TRANSITION",
            f"cannot close a stand in status {stand['status']}")
    for o in DB.orders.values():
        if o["stand_id"] == stand_id and o["queue_status"] in (
                "QUEUED", "MERGED", "AT_WINDOW"):
            err("ERR_STAND_INVALID_TRANSITION",
                "queue not drained: orders are still in flight")
    stand["status"] = "CLOSED"
    touch(stand)
    return success(stand, 200)


@app.get("/stands/<stand_id>/royalty-statement")
def royalty_statement(stand_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator"})
    stand = get_stand(stand_id)
    month = request.args.get("month")
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        err("ERR_INVALID_PAYLOAD", "month query parameter must be YYYY-MM")
    year, mon = int(month[:4]), int(month[5:7])
    if not (1 <= mon <= 12):
        err("ERR_INVALID_PAYLOAD", "month query parameter must be YYYY-MM")
    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    if mon == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)
    gross = 0
    for p in DB.payments.values():
        if p.get("captured_at") is None:
            continue
        order = DB.orders.get(p["order_id"])
        if order is None or order["stand_id"] != stand["id"]:
            continue
        captured_at = parse_dt(p["captured_at"])
        if start <= captured_at < end:
            gross += p["captured_cents"] - p["refunded_cents"]
    brand_fund = round_half_up_cents(Decimal(gross) * Decimal("0.02"))
    net = gross - brand_fund
    if gross >= 5_000_000:
        rate = Decimal("0.06")
    elif gross >= 1_000_000:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.04")
    royalty = round_half_up_cents(Decimal(net) * rate)
    return success({
        "month": month,
        "gross_cents": gross,
        "brand_fund_cents": brand_fund,
        "net_cents": net,
        "royalty_rate": float(rate),
        "royalty_cents": royalty,
    }, 200)


# ---------------------------------------------------------------------------
# Crew members (PRD §3.5)
# ---------------------------------------------------------------------------

@app.post("/crew-members")
def create_crew_member():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"full_name", "home_stand_id", "hired_on",
                        "food_handler_cert_expires_on"})
    full_name = req_str(body, "full_name")
    home_stand_id = body.get("home_stand_id")
    if not isinstance(home_stand_id, str):
        err("ERR_INVALID_PAYLOAD", "home_stand_id is required")
    get_stand(home_stand_id)  # body FK existence
    hired_on = body.get("hired_on")
    parse_date(hired_on, "hired_on")
    cert = body.get("food_handler_cert_expires_on")
    parse_date(cert, "food_handler_cert_expires_on")
    rec = {
        "full_name": full_name,
        "home_stand_id": home_stand_id,
        "hired_on": hired_on,
        "food_handler_cert_expires_on": cert,
    }
    touch(rec, created=True)
    DB.crew_members[rec["id"]] = rec
    return success(rec, 201)


@app.get("/crew-members/<crew_member_id>")
def read_crew_member(crew_member_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    return success(get_crew(crew_member_id), 200)


@app.get("/crew-members")
def list_crew_members():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead"})
    home_stand_id = request.args.get("home_stand_id")
    rows = list(DB.crew_members.values())
    if home_stand_id is not None:
        rows = [c for c in rows if c["home_stand_id"] == home_stand_id]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.patch("/crew-members/<crew_member_id>")
def update_crew_member(crew_member_id):
    auth({"PlatformAdmin"})
    member = get_crew(crew_member_id)
    body = get_json()
    forbid_extra(body, {"food_handler_cert_expires_on"})
    if "food_handler_cert_expires_on" in body:
        v = body["food_handler_cert_expires_on"]
        parse_date(v, "food_handler_cert_expires_on")
        member["food_handler_cert_expires_on"] = v
    touch(member)
    return success(member, 200)


# ---------------------------------------------------------------------------
# Operator agreements (PRD §3.2)
# ---------------------------------------------------------------------------

@app.post("/operator-agreements")
def create_agreement():
    user_id, _ = auth({"RegionalManager"})
    body = get_json()
    forbid_extra(body, {"stand_id", "crew_member_id", "revenue_share_pct"})
    stand_id = body.get("stand_id")
    crew_member_id = body.get("crew_member_id")
    if not isinstance(stand_id, str):
        err("ERR_INVALID_PAYLOAD", "stand_id is required")
    if not isinstance(crew_member_id, str):
        err("ERR_INVALID_PAYLOAD", "crew_member_id is required")
    get_stand(stand_id)          # body FK existence, left to right
    member = get_crew(crew_member_id)
    pct = req_number(body, "revenue_share_pct")
    if not (0 < pct < 1):
        err("ERR_INVALID_PAYLOAD", "revenue_share_pct must lie strictly in (0, 1)")
    # Priority 8: certification safety before priority 10: tenure.
    if parse_date(member["food_handler_cert_expires_on"]) <= clock_date():
        err("ERR_CERTIFICATION_EXPIRED",
            "food-handler certification is expired at the current logical clock date")
    tenure_days = (clock_date() - parse_date(member["hired_on"])).days
    if tenure_days < 365:
        err("ERR_TENURE_INSUFFICIENT",
            f"operator nominee tenure {tenure_days} days < 365")
    rec = {
        "stand_id": stand_id,
        "crew_member_id": crew_member_id,
        "revenue_share_pct": pct,
        "nominated_by": user_id,
        "approved_by": None,
        "activated_on": None,
        "status": "NOMINATED",
    }
    touch(rec, created=True)
    DB.agreements[rec["id"]] = rec
    return success(rec, 201)


@app.get("/operator-agreements/<agreement_id>")
def read_agreement(agreement_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator"})
    return success(get_agreement(agreement_id), 200)


@app.get("/operator-agreements")
def list_agreements():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator"})
    rows = list(DB.agreements.values())
    stand_id = request.args.get("stand_id")
    crew_member_id = request.args.get("crew_member_id")
    status = request.args.get("status")
    if stand_id is not None:
        rows = [a for a in rows if a["stand_id"] == stand_id]
    if crew_member_id is not None:
        rows = [a for a in rows if a["crew_member_id"] == crew_member_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/operator-agreements/<agreement_id>/approve")
def approve_agreement(agreement_id):
    user_id, _ = auth({"PlatformAdmin"})
    ag = get_agreement(agreement_id)
    if ag["status"] != "NOMINATED":
        err("ERR_AGREEMENT_INVALID_STATE", "only a NOMINATED agreement can be approved")
    if user_id == ag["nominated_by"]:
        err("ERR_SEGREGATION_OF_DUTIES", "the approver must differ from the nominator")
    ag["status"] = "APPROVED"
    ag["approved_by"] = user_id
    touch(ag)
    return success(ag, 200)


@app.post("/operator-agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    user_id, _ = auth({"StandOperator"})
    ag = get_agreement(agreement_id)
    if user_id != ag["crew_member_id"]:
        err("ERR_UNAUTHORIZED_ROLE",
            "only the selected operator may activate their agreement")
    if ag["status"] != "APPROVED":
        err("ERR_AGREEMENT_INVALID_STATE", "only an APPROVED agreement can be activated")
    if active_agreement_for_stand(ag["stand_id"]) is not None:
        err("ERR_AGREEMENT_INVALID_STATE",
            "another ACTIVE agreement already exists for this stand")
    ag["status"] = "ACTIVE"
    ag["activated_on"] = clock_date().isoformat()
    touch(ag)
    return success(ag, 200)


@app.post("/operator-agreements/<agreement_id>/suspend")
def suspend_agreement(agreement_id):
    auth({"RegionalManager"})
    ag = get_agreement(agreement_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_INVALID_STATE", "only an ACTIVE agreement can be suspended")
    ag["status"] = "SUSPENDED"
    touch(ag)
    if active_agreement_for_stand(ag["stand_id"]) is None:
        stand = DB.stands.get(ag["stand_id"])
        if stand is not None:
            suspend_stand_cascade(stand)
    return success(ag, 200)


@app.post("/operator-agreements/<agreement_id>/reinstate")
def reinstate_agreement(agreement_id):
    auth({"RegionalManager"})
    ag = get_agreement(agreement_id)
    if ag["status"] != "SUSPENDED":
        err("ERR_AGREEMENT_INVALID_STATE", "only a SUSPENDED agreement can be reinstated")
    if active_agreement_for_stand(ag["stand_id"]) is not None:
        err("ERR_AGREEMENT_INVALID_STATE",
            "another ACTIVE agreement already exists for this stand")
    ag["status"] = "ACTIVE"
    touch(ag)
    return success(ag, 200)


@app.post("/operator-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    auth({"RegionalManager"})
    ag = get_agreement(agreement_id)
    if ag["status"] not in ("ACTIVE", "SUSPENDED"):
        err("ERR_AGREEMENT_INVALID_STATE",
            "only an ACTIVE or SUSPENDED agreement can be terminated")
    ag["status"] = "TERMINATED"
    touch(ag)
    if active_agreement_for_stand(ag["stand_id"]) is None:
        stand = DB.stands.get(ag["stand_id"])
        if stand is not None:
            suspend_stand_cascade(stand)
    return success(ag, 200)


# ---------------------------------------------------------------------------
# Recipes (PRD §3.3)
# ---------------------------------------------------------------------------

RECIPE_CHANNELS = {"CORE", "SEASONAL", "SECRET"}
TEMP_CLASSES = {"HOT", "ICED", "BLENDED"}


@app.post("/recipes")
def create_recipe():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"name", "channel", "base_price_cents", "base_build_seconds",
                        "temperature_class", "season_start", "season_end", "modifiers"})
    name = req_str(body, "name")
    channel = req_str(body, "channel")
    if channel not in RECIPE_CHANNELS:
        err("ERR_INVALID_PAYLOAD", f"channel must be one of {sorted(RECIPE_CHANNELS)}")
    base_price = req_int(body, "base_price_cents")
    if base_price < 1:
        err("ERR_INVALID_PAYLOAD", "base_price_cents must be >= 1")
    base_build = req_int(body, "base_build_seconds")
    if base_build < 1:
        err("ERR_INVALID_PAYLOAD", "base_build_seconds must be >= 1")
    temp = req_str(body, "temperature_class")
    if temp not in TEMP_CLASSES:
        err("ERR_INVALID_PAYLOAD", f"temperature_class must be one of {sorted(TEMP_CLASSES)}")
    season_start = body.get("season_start")
    season_end = body.get("season_end")
    if channel == "SEASONAL":
        if season_start is None or season_end is None:
            err("ERR_INVALID_PAYLOAD",
                "SEASONAL recipes require season_start and season_end")
        ss = parse_date(season_start, "season_start")
        se = parse_date(season_end, "season_end")
        if se <= ss:
            err("ERR_INVALID_PAYLOAD", "season_end must be strictly after season_start")
    else:
        if season_start is not None or season_end is not None:
            err("ERR_INVALID_PAYLOAD",
                "season_start/season_end are only valid on SEASONAL recipes")
    modifiers = body.get("modifiers", [])
    if not isinstance(modifiers, list):
        err("ERR_INVALID_PAYLOAD", "modifiers must be an array")
    mods = []
    seen = set()
    for m in modifiers:
        if not isinstance(m, dict):
            err("ERR_INVALID_PAYLOAD", "each modifier must be an object")
        mname = m.get("name")
        if not isinstance(mname, str) or not mname.strip():
            err("ERR_INVALID_PAYLOAD", "modifier name must be a non-empty string")
        if mname in seen:
            err("ERR_INVALID_PAYLOAD", "modifier names must be unique within a recipe")
        seen.add(mname)
        price = m.get("price_cents")
        if isinstance(price, bool) or not isinstance(price, int):
            err("ERR_INVALID_PAYLOAD", "modifier price_cents must be an integer")
        adder = m.get("build_seconds_adder")
        if isinstance(adder, bool) or not isinstance(adder, int):
            err("ERR_INVALID_PAYLOAD", "modifier build_seconds_adder must be an integer")
        mods.append({"name": mname, "price_cents": price,
                     "build_seconds_adder": adder})
    rec = {
        "name": name,
        "channel": channel,
        "base_price_cents": base_price,
        "base_build_seconds": base_build,
        "temperature_class": temp,
        "season_start": season_start,
        "season_end": season_end,
        "modifiers": mods,
        "status": "ACTIVE",
    }
    touch(rec, created=True)
    DB.recipes[rec["id"]] = rec
    return success(rec, 201)


@app.get("/recipes/<recipe_id>")
def read_recipe(recipe_id):
    auth(VALID_ROLES)
    return success(get_recipe(recipe_id), 200)


@app.post("/recipes/<recipe_id>/retire")
def retire_recipe(recipe_id):
    auth({"PlatformAdmin"})
    recipe = get_recipe(recipe_id)
    if recipe["status"] != "ACTIVE":
        err("ERR_INVALID_PAYLOAD", "only an ACTIVE recipe can be retired")
    for d in DB.distributions.values():
        if d["recipe_id"] == recipe_id and d["status"] in (
                "STAGED", "ACTIVATED", "SUSPENDED"):
            err("ERR_RECIPE_HAS_ACTIVE_DISTRIBUTIONS",
                "all distributions must be WITHDRAWN before retiring the recipe")
    recipe["status"] = "RETIRED"
    touch(recipe)
    return success(recipe, 200)


# ---------------------------------------------------------------------------
# Recipe distributions (PRD §3.3)
# ---------------------------------------------------------------------------

@app.post("/recipe-distributions")
def create_distribution():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"recipe_id", "stand_id"})
    recipe_id = body.get("recipe_id")
    stand_id = body.get("stand_id")
    if not isinstance(recipe_id, str):
        err("ERR_INVALID_PAYLOAD", "recipe_id is required")
    if not isinstance(stand_id, str):
        err("ERR_INVALID_PAYLOAD", "stand_id is required")
    get_recipe(recipe_id)
    get_stand(stand_id)
    rec = {"recipe_id": recipe_id, "stand_id": stand_id, "status": "STAGED"}
    touch(rec, created=True)
    DB.distributions[rec["id"]] = rec
    return success(rec, 201)


@app.get("/recipe-distributions/<distribution_id>")
def read_distribution(distribution_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    return success(get_distribution(distribution_id), 200)


@app.get("/recipe-distributions")
def list_distributions():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.distributions.values())
    recipe_id = request.args.get("recipe_id")
    stand_id = request.args.get("stand_id")
    status = request.args.get("status")
    if recipe_id is not None:
        rows = [d for d in rows if d["recipe_id"] == recipe_id]
    if stand_id is not None:
        rows = [d for d in rows if d["stand_id"] == stand_id]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/recipe-distributions/<distribution_id>/activate")
def activate_distribution(distribution_id):
    auth({"StandOperator"})
    dist = get_distribution(distribution_id)
    if dist["status"] not in ("STAGED", "SUSPENDED"):
        err("ERR_DISTRIBUTION_INVALID_STATE",
            "only a STAGED or SUSPENDED distribution can be activated")
    recipe = DB.recipes.get(dist["recipe_id"])
    if recipe is None or recipe["status"] != "ACTIVE":
        err("ERR_DISTRIBUTION_INVALID_STATE",
            "a distribution of a retired recipe cannot be activated")
    dist["status"] = "ACTIVATED"
    touch(dist)
    return success(dist, 200)


@app.post("/recipe-distributions/<distribution_id>/suspend")
def suspend_distribution(distribution_id):
    auth({"StandOperator"})
    dist = get_distribution(distribution_id)
    if dist["status"] != "ACTIVATED":
        err("ERR_DISTRIBUTION_INVALID_STATE",
            "only an ACTIVATED distribution can be suspended")
    dist["status"] = "SUSPENDED"
    touch(dist)
    return success(dist, 200)


@app.post("/recipe-distributions/<distribution_id>/withdraw")
def withdraw_distribution(distribution_id):
    auth({"StandOperator"})
    dist = get_distribution(distribution_id)
    if dist["status"] not in ("ACTIVATED", "SUSPENDED"):
        err("ERR_DISTRIBUTION_INVALID_STATE",
            "only an ACTIVATED or SUSPENDED distribution can be withdrawn")
    dist["status"] = "WITHDRAWN"
    touch(dist)
    # Cascade: cancel PENDING/BUILDING items at this stand referencing this recipe.
    affected_orders = set()
    for item in DB.order_items.values():
        if item["recipe_id"] != dist["recipe_id"]:
            continue
        if item["build_status"] not in ("PENDING", "BUILDING"):
            continue
        order = DB.orders.get(item["order_id"])
        if order is None or order["stand_id"] != dist["stand_id"]:
            continue
        item["build_status"] = "CANCELLED"
        touch(item)
        affected_orders.add(order["id"])
    for oid in affected_orders:
        order = DB.orders[oid]
        recompute_order_totals(order)
        touch(order)
    return success(dist, 200)


# ---------------------------------------------------------------------------
# Loyalty accounts (PRD §3.4)
# ---------------------------------------------------------------------------

@app.post("/loyalty-accounts")
def create_loyalty_account():
    auth({"PlatformAdmin"})
    body = get_json()
    forbid_extra(body, {"full_name", "home_stand_id"})
    full_name = req_str(body, "full_name")
    home_stand_id = body.get("home_stand_id")
    if not isinstance(home_stand_id, str):
        err("ERR_INVALID_PAYLOAD", "home_stand_id is required")
    get_stand(home_stand_id)
    rec = {
        "full_name": full_name,
        "home_stand_id": home_stand_id,
        "points": 0,
        "tier": "NONE",
        "lifetime_captured_cents": 0,
    }
    touch(rec, created=True)
    DB.loyalty_accounts[rec["id"]] = rec
    return success(rec, 201)


@app.get("/loyalty-accounts/<account_id>")
def read_loyalty_account(account_id):
    auth(VALID_ROLES)
    return success(get_account(account_id), 200)


@app.get("/loyalty-accounts")
def list_loyalty_accounts():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead"})
    rows = list(DB.loyalty_accounts.values())
    home_stand_id = request.args.get("home_stand_id")
    tier = request.args.get("tier")
    if home_stand_id is not None:
        rows = [a for a in rows if a["home_stand_id"] == home_stand_id]
    if tier is not None:
        rows = [a for a in rows if a["tier"] == tier]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/loyalty-accounts/<account_id>/points-adjustments")
def points_adjustment(account_id):
    auth({"PlatformAdmin", "StandOperator"})
    account = get_account(account_id)
    body = get_json()
    forbid_extra(body, {"delta_points", "reason"})
    delta = req_int(body, "delta_points")
    req_str(body, "reason")
    apply_points(account, delta)
    return success(account, 200)


# ---------------------------------------------------------------------------
# Shifts and assignments (PRD §3.5)
# ---------------------------------------------------------------------------

ASSIGNMENT_ROLES = {"TAKER", "BAR", "RUNNER", "LEAD"}


@app.post("/shifts")
def create_shift():
    auth({"StandOperator"})
    body = get_json()
    forbid_extra(body, {"stand_id", "starts_at", "ends_at", "is_peak"})
    stand_id = body.get("stand_id")
    if not isinstance(stand_id, str):
        err("ERR_INVALID_PAYLOAD", "stand_id is required")
    get_stand(stand_id)
    starts_at = req_str(body, "starts_at")
    ends_at = req_str(body, "ends_at")
    is_peak = req_bool(body, "is_peak")
    starts = parse_dt(starts_at, "starts_at")
    ends = parse_dt(ends_at, "ends_at")
    if ends <= starts:
        err("ERR_INVALID_TIME_RANGE", "ends_at must be strictly after starts_at")
    if starts <= DB.clock:
        err("ERR_SHIFT_IN_PAST", "starts_at must be after the current logical clock")
    rec = {
        "stand_id": stand_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "is_peak": is_peak,
        "status": "DRAFT",
        "provisional_deficit_score": None,
        "reconciled_deficit_score": None,
    }
    touch(rec, created=True)
    DB.shifts[rec["id"]] = rec
    return success(rec, 201)


@app.get("/shifts/<shift_id>")
def read_shift(shift_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    return success(get_shift(shift_id), 200)


@app.get("/shifts")
def list_shifts():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.shifts.values())
    stand_id = request.args.get("stand_id")
    status = request.args.get("status")
    if stand_id is not None:
        rows = [s for s in rows if s["stand_id"] == stand_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/shifts/<shift_id>/assignments")
def create_assignment(shift_id):
    auth({"StandOperator"})
    shift = get_shift(shift_id)
    body = get_json()
    forbid_extra(body, {"crew_member_id", "role", "starts_at", "ends_at",
                        "expected_shift_version"})
    crew_member_id = body.get("crew_member_id")
    if not isinstance(crew_member_id, str):
        err("ERR_INVALID_PAYLOAD", "crew_member_id is required")
    member = get_crew(crew_member_id)  # body FK existence
    role = req_str(body, "role")
    if role not in ASSIGNMENT_ROLES:
        err("ERR_INVALID_PAYLOAD", f"role must be one of {sorted(ASSIGNMENT_ROLES)}")
    starts_at = req_str(body, "starts_at")
    ends_at = req_str(body, "ends_at")
    if "expected_shift_version" not in body:
        err("ERR_INVALID_PAYLOAD", "expected_shift_version is required")
    expected = body["expected_shift_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_PAYLOAD", "expected_shift_version must be an integer")
    starts = parse_dt(starts_at, "starts_at")
    ends = parse_dt(ends_at, "ends_at")
    # Priority 5: OCC
    if expected != shift["version"]:
        err("ERR_STALE_VERSION", "expected_shift_version does not match the shift version")
    # Priority 6: state
    if shift["status"] != "DRAFT":
        err("ERR_SHIFT_INVALID_STATE", "assignments may only be added to a DRAFT shift")
    # Priority 8: certification safety
    if parse_date(member["food_handler_cert_expires_on"]) <= clock_date():
        err("ERR_CERTIFICATION_EXPIRED",
            "food-handler certification is expired at the current logical clock date")
    # Priority 9: overlap (half-open intervals; adjacency allowed)
    for a in DB.assignments.values():
        if a["crew_member_id"] != crew_member_id or a["status"] == "CANCELLED":
            continue
        a_start = parse_dt(a["starts_at"])
        a_end = parse_dt(a["ends_at"])
        if starts < a_end and a_start < ends:
            err("ERR_ASSIGNMENT_OVERLAP",
                "crew member already has a non-cancelled overlapping assignment")
    # Priority 10: time range, rotation stretch, shift bounds
    if ends <= starts:
        err("ERR_INVALID_TIME_RANGE", "ends_at must be strictly after starts_at")
    if (ends - starts).total_seconds() > 120 * 60:
        err("ERR_ROTATION_STRETCH_EXCEEDED", "a single assignment may not exceed 120 minutes")
    shift_start = parse_dt(shift["starts_at"])
    shift_end = parse_dt(shift["ends_at"])
    if starts < shift_start or ends > shift_end:
        err("ERR_ASSIGNMENT_OUTSIDE_SHIFT",
            "assignment interval must lie within the shift bounds")
    rec = {
        "shift_id": shift_id,
        "crew_member_id": crew_member_id,
        "role": role,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "ASSIGNED",
    }
    touch(rec, created=True)
    DB.assignments[rec["id"]] = rec
    touch(shift)  # each successful addition increments Shift.version by one
    return success(rec, 201)


@app.get("/shift-assignments/<assignment_id>")
def read_assignment(assignment_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    return success(get_assignment(assignment_id), 200)


@app.get("/shift-assignments")
def list_assignments():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.assignments.values())
    shift_id = request.args.get("shift_id")
    crew_member_id = request.args.get("crew_member_id")
    status = request.args.get("status")
    if shift_id is not None:
        rows = [a for a in rows if a["shift_id"] == shift_id]
    if crew_member_id is not None:
        rows = [a for a in rows if a["crew_member_id"] == crew_member_id]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/shift-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    auth({"StandOperator"})
    assignment = get_assignment(assignment_id)
    if assignment["status"] != "ASSIGNED":
        err("ERR_ASSIGNMENT_INVALID_STATE", "only an ASSIGNED assignment can be cancelled")
    shift = get_shift(assignment["shift_id"])
    if shift["status"] not in ("DRAFT", "PUBLISHED"):
        err("ERR_SHIFT_INVALID_STATE",
            "assignments may be cancelled only while the shift is DRAFT or PUBLISHED")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    return success(assignment, 200)


@app.post("/shift-assignments/<assignment_id>/check-in")
def check_in_assignment(assignment_id):
    user_id, _ = auth({"CrewMember"})
    assignment = get_assignment(assignment_id)
    if user_id != assignment["crew_member_id"]:
        err("ERR_UNAUTHORIZED_ROLE", "a crew member may check in only to their own assignment")
    if assignment["status"] != "ASSIGNED":
        err("ERR_ASSIGNMENT_INVALID_STATE", "only an ASSIGNED assignment can be checked in")
    shift = get_shift(assignment["shift_id"])
    if shift["status"] != "IN_PROGRESS":
        err("ERR_SHIFT_INVALID_STATE", "check-in requires the parent shift to be IN_PROGRESS")
    assignment["status"] = "CHECKED_IN"
    touch(assignment)
    return success(assignment, 200)


@app.post("/shifts/<shift_id>/publish")
def publish_shift(shift_id):
    auth({"StandOperator"})
    shift = get_shift(shift_id)
    if shift["status"] != "DRAFT":
        err("ERR_SHIFT_INVALID_STATE", "only a DRAFT shift can be published")
    if active_agreement_for_stand(shift["stand_id"]) is None:
        err("ERR_AGREEMENT_NOT_ACTIVE",
            "an ACTIVE operator agreement is required to publish the shift")
    planned = [a for a in DB.assignments.values()
               if a["shift_id"] == shift_id and a["status"] in ("ASSIGNED", "CHECKED_IN")]
    if shift["is_peak"] and len(planned) < 4:
        err("ERR_PEAK_STAFFING_INSUFFICIENT",
            "a peak shift requires at least 4 non-cancelled assignments at publish")
    required = 4 if shift["is_peak"] else 2
    confirmed = len(planned)
    has_lead = any(a["role"] == "LEAD" for a in planned)
    shift["provisional_deficit_score"] = (
        max(0, required - confirmed) * 10 + (0 if has_lead else 25)
    )
    shift["status"] = "PUBLISHED"
    touch(shift)
    return success(shift, 200)


@app.post("/shifts/<shift_id>/start")
def start_shift(shift_id):
    auth({"StandOperator"})
    shift = get_shift(shift_id)
    if shift["status"] != "PUBLISHED":
        err("ERR_SHIFT_INVALID_STATE", "only a PUBLISHED shift can be started")
    if DB.clock < parse_dt(shift["starts_at"]):
        err("ERR_SHIFT_INVALID_STATE",
            "the shift cannot be started before its starts_at")
    shift["status"] = "IN_PROGRESS"
    touch(shift)
    return success(shift, 200)


@app.post("/shifts/<shift_id>/reconcile")
def reconcile_shift(shift_id):
    auth({"StandOperator"})
    shift = get_shift(shift_id)
    if shift["status"] != "IN_PROGRESS":
        err("ERR_SHIFT_INVALID_STATE", "only an IN_PROGRESS shift can be reconciled")
    if DB.clock < parse_dt(shift["ends_at"]):
        err("ERR_SHIFT_INVALID_STATE", "the shift cannot be reconciled before its ends_at")
    for a in DB.assignments.values():
        if a["shift_id"] == shift_id and a["status"] == "ASSIGNED":
            a["status"] = "NO_SHOW"
            touch(a)
    required = 4 if shift["is_peak"] else 2
    related = [a for a in DB.assignments.values() if a["shift_id"] == shift_id]
    checked_in = [a for a in related if a["status"] == "CHECKED_IN"]
    no_shows = [a for a in related if a["status"] == "NO_SHOW"]
    has_ci_lead = any(a["role"] == "LEAD" for a in checked_in)
    shift["reconciled_deficit_score"] = (
        max(0, required - len(checked_in)) * 10
        + (0 if has_ci_lead else 25)
        + len(no_shows) * 5
    )
    shift["status"] = "RECONCILED"
    touch(shift)
    return success(shift, 200)


@app.post("/shifts/<shift_id>/lock")
def lock_shift(shift_id):
    auth({"StandOperator"})
    shift = get_shift(shift_id)
    if shift["status"] != "RECONCILED":
        err("ERR_SHIFT_INVALID_STATE", "only a RECONCILED shift can be locked")
    shift["status"] = "LOCKED"
    touch(shift)
    return success(shift, 200)


# ---------------------------------------------------------------------------
# Orders (PRD §3.6)
# ---------------------------------------------------------------------------

def crew_on_bar(stand_id):
    """Checked-in BAR crew on the stand's IN_PROGRESS shift (default 2)."""
    for s in DB.shifts.values():
        if s["stand_id"] == stand_id and s["status"] == "IN_PROGRESS":
            count = 0
            for a in DB.assignments.values():
                if (a["shift_id"] == s["id"] and a["role"] == "BAR"
                        and a["status"] == "CHECKED_IN"):
                    count += 1
            return count
    return 2


def compute_build_time_seconds(recipe, modifier_names, stand_id):
    mods = {m["name"]: m for m in recipe["modifiers"]}
    base = recipe["base_build_seconds"] + sum(
        mods[n]["build_seconds_adder"] for n in modifier_names
    )
    if recipe["temperature_class"] == "BLENDED":
        base += 15
    bar = crew_on_bar(stand_id)
    if bar >= 3:
        multiplier = Decimal("0.8")
    elif bar == 2:
        multiplier = Decimal("1.0")
    else:
        multiplier = Decimal("1.3")
    scaled = (Decimal(base) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return min(240, int(scaled))


@app.post("/orders")
def create_order():
    user_id, role = auth({"CrewMember", "ShiftLead", "LoyaltyCustomer"})
    body = get_json()
    forbid_extra(body, {"stand_id", "source", "lane_code", "loyalty_account_id",
                        "items", "expected_stand_version"})
    stand_id = body.get("stand_id")
    if not isinstance(stand_id, str):
        err("ERR_INVALID_PAYLOAD", "stand_id is required")
    stand = get_stand(stand_id)  # body FK existence
    source = body.get("source")
    if source not in ("WINDOW", "LOYALTY_APP"):
        err("ERR_INVALID_PAYLOAD", "source must be WINDOW or LOYALTY_APP")
    lane_code = body.get("lane_code")
    loyalty_account_id = body.get("loyalty_account_id")
    if source == "WINDOW":
        if not isinstance(lane_code, str) or not lane_code.strip():
            err("ERR_INVALID_PAYLOAD", "WINDOW orders require a lane_code")
        if lane_config(stand, lane_code) is None:
            err("ERR_INVALID_PAYLOAD", f"lane {lane_code} is not configured at this stand")
    else:
        if not isinstance(loyalty_account_id, str):
            err("ERR_INVALID_PAYLOAD", "LOYALTY_APP orders require a loyalty_account_id")
    if loyalty_account_id is not None and not isinstance(loyalty_account_id, str):
        err("ERR_INVALID_PAYLOAD", "loyalty_account_id must be a string")
    items = body.get("items")
    if not isinstance(items, list):
        err("ERR_INVALID_PAYLOAD", "items must be an array")
    if "expected_stand_version" not in body:
        err("ERR_INVALID_PAYLOAD", "expected_stand_version is required")
    expected = body["expected_stand_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_PAYLOAD", "expected_stand_version must be an integer")

    # Body FK: loyalty account (priority 3)
    account = None
    if loyalty_account_id is not None:
        account = get_account(loyalty_account_id)

    # Priority 2 ownership: a LoyaltyCustomer may order only on their own account.
    if role == "LoyaltyCustomer":
        if source != "LOYALTY_APP" or loyalty_account_id != user_id:
            err("ERR_UNAUTHORIZED_ROLE",
                "loyalty customers may place only their own app-ahead orders")

    # Priority 4: item shape, quantities, modifier names
    recipes = []
    for item in items:
        if not isinstance(item, dict):
            err("ERR_INVALID_PAYLOAD", "each item must be an object")
        recipe_id = item.get("recipe_id")
        if not isinstance(recipe_id, str):
            err("ERR_INVALID_PAYLOAD", "each item requires a recipe_id")
        recipe = get_recipe(recipe_id)  # body FK existence
        quantity = item.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            err("ERR_INVALID_PAYLOAD", "quantity must be an integer")
        if quantity < 1:
            err("ERR_INVALID_QUANTITY", "quantity must be at least 1")
        modifier_names = item.get("modifier_names", [])
        if not isinstance(modifier_names, list) or not all(
                isinstance(n, str) for n in modifier_names):
            err("ERR_INVALID_PAYLOAD", "modifier_names must be an array of strings")
        declared = {m["name"] for m in recipe["modifiers"]}
        for n in modifier_names:
            if n not in declared:
                err("ERR_MODIFIER_UNKNOWN", f"unknown modifier {n!r} on recipe {recipe['name']}")
        recipes.append((recipe, quantity, modifier_names))

    # Priority 5: OCC on stand version
    if expected != stand["version"]:
        err("ERR_STALE_VERSION", "expected_stand_version does not match the stand version")

    # Priority 7: stand posture gating
    if source == "WINDOW":
        if stand["status"] not in ("OPEN", "THROTTLED"):
            err("ERR_STAND_NOT_ACCEPTING_ORDERS",
                "window orders require the stand to be OPEN or THROTTLED")
    else:
        if stand["status"] != "OPEN":
            err("ERR_STAND_NOT_ACCEPTING_ORDERS",
                "app-ahead orders require the stand to be OPEN")

    # Priority 9: seasonal bounds (half-open [season_start, season_end))
    today = clock_date()
    for recipe, _qty, _mods in recipes:
        if recipe["channel"] == "SEASONAL":
            ss = parse_date(recipe["season_start"])
            se = parse_date(recipe["season_end"])
            if not (ss <= today < se):
                err("ERR_RECIPE_OUT_OF_SEASON",
                    f"recipe {recipe['name']} is out of season at the current logical clock date")

    # Priority 10: order contents, lane capacity
    if not items:
        err("ERR_EMPTY_ORDER", "an order requires at least one item")
    if source == "WINDOW":
        cfg = lane_config(stand, lane_code)
        if lane_occupancy(stand, lane_code) >= cfg["max_stack_cars"]:
            err("ERR_LANE_STACKING_FULL", f"lane {lane_code} has no free stacking slot")

    # Priority 11: distribution liveness, secret tier
    for recipe, _qty, _mods in recipes:
        live = any(
            d["recipe_id"] == recipe["id"] and d["stand_id"] == stand["id"]
            and d["status"] == "ACTIVATED"
            for d in DB.distributions.values()
        )
        if not live:
            err("ERR_DISTRIBUTION_NOT_ACTIVE",
                f"recipe {recipe['name']} has no ACTIVATED distribution at this stand")
        if recipe["channel"] == "SECRET":
            if account is None or account["tier"] != "GOLD":
                err("ERR_SECRET_MENU_TIER_REQUIRED",
                    "SECRET recipes require a GOLD loyalty tier account")

    # Build the order
    order = {
        "stand_id": stand["id"],
        "loyalty_account_id": loyalty_account_id,
        "source": source,
        "lane_code": None,
        "lane_seq": None,
        "queue_status": "QUEUED",
        "payment_status": "UNPAID",
        "build_status": "QUEUED",
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "outstanding_build_seconds": 0,
        "handoff_at": None,
    }
    touch(order, created=True)
    DB.orders[order["id"]] = order

    pct = tier_pct(account["tier"]) if account is not None else Decimal("0")
    for recipe, quantity, modifier_names in recipes:
        mods = {m["name"]: m for m in recipe["modifiers"]}
        unit_price = recipe["base_price_cents"] + sum(
            mods[n]["price_cents"] for n in modifier_names
        )
        line_gross = unit_price * quantity
        line_discount = round_half_up_cents(Decimal(line_gross) * pct)
        item_rec = {
            "order_id": order["id"],
            "recipe_id": recipe["id"],
            "quantity": quantity,
            "modifier_names": list(modifier_names),
            "unit_price_cents": unit_price,
            "line_gross_cents": line_gross,
            "line_discount_cents": line_discount,
            "line_net_cents": line_gross - line_discount,
            "build_time_seconds": compute_build_time_seconds(
                recipe, modifier_names, stand["id"]),
            "build_status": "PENDING",
        }
        touch(item_rec, created=True)
        DB.order_items[item_rec["id"]] = item_rec

    if source == "WINDOW":
        order["lane_code"] = lane_code
        order["lane_seq"] = next_lane_seq(stand["id"], lane_code)
        order["queue_status"] = "MERGED"

    recompute_order_totals(order)
    touch(order)
    recompute_lane_occupancy(stand)
    touch(stand)  # every successful create bumps Stand.version by one
    return success(order, 201)


@app.get("/orders/<order_id>")
def read_order(order_id):
    auth(VALID_ROLES)
    return success(get_order(order_id), 200)


@app.get("/orders")
def list_orders():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.orders.values())
    stand_id = request.args.get("stand_id")
    loyalty_account_id = request.args.get("loyalty_account_id")
    queue_status = request.args.get("queue_status")
    if stand_id is not None:
        rows = [o for o in rows if o["stand_id"] == stand_id]
    if loyalty_account_id is not None:
        rows = [o for o in rows if o["loyalty_account_id"] == loyalty_account_id]
    if queue_status is not None:
        rows = [o for o in rows if o["queue_status"] == queue_status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/orders/<order_id>/merge")
def merge_order(order_id):
    user_id, _ = auth({"LoyaltyCustomer"})
    order = get_order(order_id)
    body = get_json()
    forbid_extra(body, {"expected_stand_version"})
    if "expected_stand_version" not in body:
        err("ERR_INVALID_PAYLOAD", "expected_stand_version is required")
    expected = body["expected_stand_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_INVALID_PAYLOAD", "expected_stand_version must be an integer")
    # Priority 2 ownership
    if order["loyalty_account_id"] != user_id:
        err("ERR_UNAUTHORIZED_ROLE", "customers may merge only their own orders")
    stand = get_stand(order["stand_id"])
    # Priority 5: OCC on stand version
    if expected != stand["version"]:
        err("ERR_STALE_VERSION", "expected_stand_version does not match the stand version")
    # Priority 6: order state
    if order["queue_status"] != "QUEUED" or order["source"] != "LOYALTY_APP":
        err("ERR_ORDER_INVALID_STATE", "only a QUEUED app-ahead order can be merged")
    # Priority 7: stand posture
    if stand["status"] not in ("OPEN", "THROTTLED"):
        err("ERR_STAND_NOT_ACCEPTING_ORDERS",
            "merging requires the stand to be OPEN or THROTTLED")
    # Priority 10: lane selector (errors ERR_LANE_STACKING_FULL when empty)
    lane = select_lane(stand)
    order["lane_code"] = lane
    order["lane_seq"] = next_lane_seq(stand["id"], lane)
    order["queue_status"] = "MERGED"
    touch(order)
    recompute_lane_occupancy(stand)
    touch(stand)
    return success(order, 200)


@app.post("/orders/<order_id>/abandon")
def abandon_order(order_id):
    auth({"ShiftLead"})
    order = get_order(order_id)
    if order["queue_status"] not in ("QUEUED", "MERGED", "AT_WINDOW"):
        err("ERR_ORDER_INVALID_STATE", "only an in-flight order can be abandoned")
    if order["payment_status"] in ("CAPTURED", "REFUND_PENDING", "REFUNDED"):
        err("ERR_ORDER_INVALID_STATE",
            "an order with settled money cannot be abandoned")
    stand = DB.stands.get(order["stand_id"])
    abandon_order_row(order)
    if stand is not None:
        recompute_lane_occupancy(stand)
        touch(stand)
    return success(order, 200)


@app.post("/orders/<order_id>/call-to-window")
def call_to_window(order_id):
    auth({"ShiftLead"})
    order = get_order(order_id)
    if order["queue_status"] != "MERGED":
        err("ERR_ORDER_INVALID_STATE", "only a MERGED order can be called to the window")
    order["queue_status"] = "AT_WINDOW"
    touch(order)
    stand = DB.stands.get(order["stand_id"])
    if stand is not None:
        recompute_lane_occupancy(stand)
        touch(stand)
    return success(order, 200)


@app.post("/orders/<order_id>/handoff")
def handoff_order(order_id):
    auth({"ShiftLead"})
    order = get_order(order_id)
    if order["queue_status"] != "AT_WINDOW":
        err("ERR_ORDER_INVALID_STATE", "only an AT_WINDOW order can be handed off")
    if order["payment_status"] != "CAPTURED":
        err("ERR_PAYMENT_INVALID_STATE", "handoff requires a CAPTURED payment")
    if order["build_status"] != "READY":
        err("ERR_ORDER_INVALID_STATE", "handoff requires the order build to be READY")
    order["queue_status"] = "SERVED"
    order["build_status"] = "HANDED_OFF"
    order["handoff_at"] = clock_iso()
    touch(order)
    stand = DB.stands.get(order["stand_id"])
    if stand is not None:
        recompute_lane_occupancy(stand)
        touch(stand)
    return success(order, 200)


# ---------------------------------------------------------------------------
# Order items (PRD §3.8)
# ---------------------------------------------------------------------------

@app.get("/order-items/<item_id>")
def read_order_item(item_id):
    auth(VALID_ROLES)
    return success(get_item(item_id), 200)


@app.get("/order-items")
def list_order_items():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.order_items.values())
    order_id = request.args.get("order_id")
    recipe_id = request.args.get("recipe_id")
    build_status = request.args.get("build_status")
    if order_id is not None:
        rows = [i for i in rows if i["order_id"] == order_id]
    if recipe_id is not None:
        rows = [i for i in rows if i["recipe_id"] == recipe_id]
    if build_status is not None:
        rows = [i for i in rows if i["build_status"] == build_status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/order-items/<item_id>/start-build")
def start_build(item_id):
    auth({"CrewMember"})
    item = get_item(item_id)
    if item["build_status"] != "PENDING":
        err("ERR_ORDER_INVALID_STATE", "only a PENDING item can start building")
    order = get_order(item["order_id"])
    if order["queue_status"] not in ("MERGED", "AT_WINDOW"):
        err("ERR_ORDER_INVALID_STATE",
            "build requires the parent order to be MERGED or AT_WINDOW")
    item["build_status"] = "BUILDING"
    touch(item)
    order["build_status"] = "BUILDING"
    recompute_order_totals(order)
    touch(order)
    return success(item, 200)


@app.post("/order-items/<item_id>/complete-build")
def complete_build(item_id):
    auth({"CrewMember"})
    item = get_item(item_id)
    if item["build_status"] != "BUILDING":
        err("ERR_ORDER_INVALID_STATE", "only a BUILDING item can be completed")
    item["build_status"] = "READY"
    touch(item)
    order = get_order(item["order_id"])
    siblings = order_items_of(order["id"])
    if all(i["build_status"] == "READY" for i in siblings):
        order["build_status"] = "READY"
    recompute_order_totals(order)
    touch(order)
    return success(item, 200)


# ---------------------------------------------------------------------------
# Payments (PRD §3.7)
# ---------------------------------------------------------------------------

@app.post("/orders/<order_id>/payments/authorize")
def authorize_payment(order_id):
    user_id, role = auth({"CrewMember", "ShiftLead", "LoyaltyCustomer"})
    order = get_order(order_id)
    body = get_json()
    forbid_extra(body, {"card_token"})
    card_token = body.get("card_token")
    if not isinstance(card_token, str) or not card_token.strip():
        err("ERR_INVALID_PAYLOAD", "card_token is required")
    # Priority 2 ownership: customers authorize only their own orders.
    if role == "LoyaltyCustomer" and order["loyalty_account_id"] != user_id:
        err("ERR_UNAUTHORIZED_ROLE", "customers may authorize only their own orders")
    # Priority 6: order state (a second authorize on a paid/abandoned order).
    if order["payment_status"] != "UNPAID":
        err("ERR_ORDER_INVALID_STATE",
            "the order already has a payment or is not payable")
    if order["queue_status"] in ("SERVED", "ABANDONED"):
        err("ERR_ORDER_INVALID_STATE", "a terminal order cannot be authorized")
    # Priority 12: decline simulation.
    if card_token == "DECLINE":
        err("ERR_PAYMENT_DECLINED", "the card was declined")
    payment = {
        "order_id": order["id"],
        "authorized_cents": order["total_cents"],
        "captured_cents": 0,
        "refunded_cents": 0,
        "status": "AUTHORIZED",
        "refund_initiated_by": None,
        "refund_decided_by": None,
        "captured_at": None,
    }
    touch(payment, created=True)
    DB.payments[payment["id"]] = payment
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(payment, 201)


@app.get("/payments/<payment_id>")
def read_payment(payment_id):
    auth(VALID_ROLES)
    return success(get_payment(payment_id), 200)


@app.get("/payments")
def list_payments():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    rows = list(DB.payments.values())
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    if order_id is not None:
        rows = [p for p in rows if p["order_id"] == order_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, meta = paginate(rows)
    return success(page, 200, pagination=meta)


@app.post("/payments/<payment_id>/capture")
def capture_payment(payment_id):
    auth({"ShiftLead"})
    payment = get_payment(payment_id)
    if payment["status"] != "AUTHORIZED":
        err("ERR_PAYMENT_INVALID_STATE", "only an AUTHORIZED payment can be captured")
    order = get_order(payment["order_id"])
    if order["queue_status"] not in ("MERGED", "AT_WINDOW"):
        err("ERR_ORDER_INVALID_STATE",
            "capture requires the order to be MERGED or AT_WINDOW")
    # Lane capture sequencing: the car ahead pays first.
    for other in DB.orders.values():
        if other["id"] == order["id"]:
            continue
        if (other["stand_id"] == order["stand_id"]
                and other.get("lane_code") == order["lane_code"]
                and other.get("lane_seq") is not None
                and order.get("lane_seq") is not None
                and other["lane_seq"] < order["lane_seq"]
                and other["queue_status"] not in ("SERVED", "ABANDONED")
                and other["payment_status"] in ("UNPAID", "AUTHORIZED")):
            err("ERR_CAPTURE_OUT_OF_SEQUENCE",
                "an earlier car in the lane is still awaiting payment")
    payment["status"] = "CAPTURED"
    payment["captured_cents"] = payment["authorized_cents"]
    payment["captured_at"] = clock_iso()
    touch(payment)
    order["payment_status"] = "CAPTURED"
    touch(order)
    if order["loyalty_account_id"] is not None:
        account = DB.loyalty_accounts.get(order["loyalty_account_id"])
        if account is not None:
            account["lifetime_captured_cents"] += payment["captured_cents"]
            apply_points(account, payment["captured_cents"] // 100)
    return success(payment, 200)


def apply_refund(payment, amount_cents, order):
    payment["refunded_cents"] += amount_cents
    if payment["refunded_cents"] == payment["captured_cents"]:
        payment["status"] = "REFUNDED"
    if order["loyalty_account_id"] is not None:
        account = DB.loyalty_accounts.get(order["loyalty_account_id"])
        if account is not None:
            apply_points(account, -(amount_cents // 100))


@app.post("/payments/<payment_id>/refunds")
def refund_payment(payment_id):
    user_id, _ = auth({"ShiftLead"})
    payment = get_payment(payment_id)
    body = get_json()
    forbid_extra(body, {"amount_cents"})
    amount = req_int(body, "amount_cents")
    if amount < 1:
        err("ERR_INVALID_PAYLOAD", "amount_cents must be a positive integer")
    if payment["status"] != "CAPTURED":
        err("ERR_PAYMENT_INVALID_STATE", "refunds require a CAPTURED payment")
    if payment["refunded_cents"] + amount > payment["captured_cents"]:
        err("ERR_REFUND_EXCEEDS_CAPTURED",
            "cumulative refunds may not exceed the captured amount")
    order = get_order(payment["order_id"])
    if amount <= 2000:
        # Auto-approved: applied immediately; REFUNDED only when fully refunded.
        apply_refund(payment, amount, order)
    else:
        payment["status"] = "REFUND_PENDING"
        payment["refund_initiated_by"] = user_id
        payment["pending_refund_cents"] = amount
    touch(payment)
    order["payment_status"] = payment["status"]
    touch(order)
    return success(payment, 200)


@app.post("/payments/<payment_id>/refund-decisions")
def refund_decision(payment_id):
    user_id, _ = auth({"StandOperator"})
    payment = get_payment(payment_id)
    body = get_json()
    forbid_extra(body, {"decision"})
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        err("ERR_INVALID_PAYLOAD", "decision must be APPROVE or REJECT")
    if payment["status"] != "REFUND_PENDING":
        err("ERR_PAYMENT_INVALID_STATE", "there is no pending refund to decide")
    if user_id == payment["refund_initiated_by"]:
        err("ERR_SEGREGATION_OF_DUTIES",
            "the refund decider must differ from the initiator")
    order = get_order(payment["order_id"])
    pending = payment.get("pending_refund_cents", 0)
    payment["refund_decided_by"] = user_id
    if decision == "APPROVE":
        payment["status"] = "CAPTURED"
        apply_refund(payment, pending, order)
    else:
        payment["status"] = "CAPTURED"
    payment["pending_refund_cents"] = 0
    touch(payment)
    order["payment_status"] = payment["status"]
    touch(order)
    return success(payment, 200)


# ---------------------------------------------------------------------------
# Throughput windows (PRD §3.1)
# ---------------------------------------------------------------------------

WINDOW_GAP_MINUTES = 15


def window_provisional_projected_cars(window):
    start = parse_dt(window["starts_at"])
    end = parse_dt(window["ends_at"])
    served = 0
    in_flight = 0
    for o in DB.orders.values():
        if o["stand_id"] != window["stand_id"]:
            continue
        if o["handoff_at"] is not None:
            handoff = parse_dt(o["handoff_at"])
            if start <= handoff < end:
                served += 1
        if o["queue_status"] in ("QUEUED", "MERGED", "AT_WINDOW"):
            in_flight += 1
    return served + in_flight


def window_public(window):
    """Serialize a window with live provisional projection while OPEN."""
    out = dict(window)
    if window["status"] == "OPEN":
        out["provisional_projected_cars"] = window_provisional_projected_cars(window)
    return out


@app.post("/throughput-windows")
def create_window():
    auth({"RegionalManager"})
    body = get_json()
    forbid_extra(body, {"stand_id", "starts_at", "ends_at", "target_cars"})
    stand_id = body.get("stand_id")
    if not isinstance(stand_id, str):
        err("ERR_INVALID_PAYLOAD", "stand_id is required")
    get_stand(stand_id)
    starts_at = req_str(body, "starts_at")
    ends_at = req_str(body, "ends_at")
    target = req_int(body, "target_cars")
    starts = parse_dt(starts_at, "starts_at")
    ends = parse_dt(ends_at, "ends_at")
    if ends <= starts:
        err("ERR_INVALID_TIME_RANGE", "ends_at must be strictly after starts_at")
    gap = timedelta(minutes=WINDOW_GAP_MINUTES)
    for w in DB.windows.values():
        if w["stand_id"] != stand_id:
            continue
        w_start = parse_dt(w["starts_at"])
        w_end = parse_dt(w["ends_at"])
        if starts < w_end and w_start < ends:
            err("ERR_WINDOW_OVERLAP", "the window overlaps an existing window")
        if w_end <= starts and (starts - w_end) < gap:
            err("ERR_WINDOW_OVERLAP",
                "windows must be separated by at least 15 minutes")
        if ends <= w_start and (w_start - ends) < gap:
            err("ERR_WINDOW_OVERLAP",
                "windows must be separated by at least 15 minutes")
    rec = {
        "stand_id": stand_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "target_cars": target,
        "status": "OPEN",
        "served_count": None,
        "provisional_projected_cars": None,
    }
    touch(rec, created=True)
    DB.windows[rec["id"]] = rec
    return success(window_public(rec), 201)


@app.get("/throughput-windows/<window_id>")
def read_window(window_id):
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead", "CrewMember"})
    return success(window_public(get_window(window_id)), 200)


@app.get("/throughput-windows")
def list_windows():
    auth({"PlatformAdmin", "RegionalManager", "StandOperator", "ShiftLead"})
    rows = list(DB.windows.values())
    stand_id = request.args.get("stand_id")
    status = request.args.get("status")
    if stand_id is not None:
        rows = [w for w in rows if w["stand_id"] == stand_id]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, meta = paginate(rows)
    return success([window_public(w) for w in page], 200, pagination=meta)


@app.post("/throughput-windows/<window_id>/close")
def close_window(window_id):
    auth({"RegionalManager"})
    window = get_window(window_id)
    if window["status"] != "OPEN":
        err("ERR_WINDOW_INVALID_STATE", "only an OPEN window can be closed")
    if DB.clock < parse_dt(window["ends_at"]):
        err("ERR_WINDOW_NOT_CLOSABLE",
            "the window cannot be closed before the logical clock reaches ends_at")
    start = parse_dt(window["starts_at"])
    end = parse_dt(window["ends_at"])
    served = 0
    for o in DB.orders.values():
        if o["stand_id"] != window["stand_id"] or o["handoff_at"] is None:
            continue
        handoff = parse_dt(o["handoff_at"])
        if start <= handoff < end:
            served += 1
    window["served_count"] = served
    stand = DB.stands.get(window["stand_id"])
    if served >= window["target_cars"]:
        window["status"] = "CLOSED_PASS"
        if stand is not None:
            stand["consecutive_breach_windows"] = 0
    else:
        window["status"] = "CLOSED_BREACH"
        if stand is not None:
            stand["consecutive_breach_windows"] += 1
    touch(window)
    if stand is not None:
        if (stand["consecutive_breach_windows"] >= 2
                and stand["status"] == "OPEN"):
            stand["status"] = "THROTTLED"
        touch(stand)
    return success(window_public(window), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
