#!/usr/bin/env python3
"""Hot-N-Ready Forecast Production & Pickup Portal API — in-memory Flask implementation."""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"StoreManager", "ShiftLead", "CrewMember", "Customer"}
STARTUP_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

MADE_AHEAD_RATIO = Decimal("0.6")
PORTAL_FEE_RATE = Decimal("0.05")
WASTE_TARGET_PCT = Decimal("5.0")
HOLD_MINUTES = 30
CODE_WINDOW_MINUTES = 45
CLEAN_MINUTES = 15
PROOF_MIN_MINUTES = 120
PROOF_MAX_MINUTES = 240
CHEESE_REST_MINUTES = 30

DAYPART_LABELS = {"LUNCH", "DINNER", "LATE_NIGHT"}
ORDER_KINDS = {"PORTAL_STANDARD", "PORTAL_PREORDER", "COUNTER"}
PORTAL_KINDS = {"PORTAL_STANDARD", "PORTAL_PREORDER"}
STATIONS = {"OVEN", "CUT_TABLE", "LOCKER_BAY", "DOUGH_PREP"}
MANUAL_DISCARD_REASONS = {"DAMAGED", "QUALITY"}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self._now = STARTUP_CLOCK

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


CLOCK = Clock()


def now():
    return CLOCK.now()


def iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str):
        raise err_validation("expected ISO8601 datetime string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        raise err_validation("invalid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# In-memory store (empty at every boot — no seeding)
# ---------------------------------------------------------------------------
db = {
    "store_days": {},
    "dayparts": {},
    "demand_events": {},
    "dough_batches": {},
    "cheese_batches": {},
    "products": {},
    "production_runs": {},
    "hold_units": {},
    "orders": {},
    "locker_slots": {},
    "waste_logs": {},
    "crew_shifts": {},
}
seq_counter = [0]  # monotonic counter for stable tie-breaking within same timestamp


def next_seq():
    seq_counter[0] += 1
    return seq_counter[0]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_validation(msg="validation error"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_invalid_state(msg="invalid state"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _ts():
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def make_meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": _ts()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "resource not found"},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"},
    }), 405


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    import traceback
    traceback.print_exc()
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }), 400


# ---------------------------------------------------------------------------
# Auth middleware (PRD §2.1)
# ---------------------------------------------------------------------------
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    return uid, role


def require_roles(*roles):
    uid, role = get_auth()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return uid, role


def require_order_ownership(order):
    """Customer role on order-scoped calls must own the order."""
    uid, role = get_auth()
    if role == "Customer" and uid != order["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer does not own this order")
    return uid, role


# ---------------------------------------------------------------------------
# Generic request helpers
# ---------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_validation("request body must be valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("request body must be a JSON object")
    return data


def parse_limit_offset():
    try:
        limit = request.args.get("limit")
        offset = request.args.get("offset")
        limit = int(limit) if limit is not None else 10
        offset = int(offset) if offset is not None else 0
    except (ValueError, TypeError):
        raise err_validation("invalid limit/offset")
    if limit < 1 or limit > 100:
        raise err_validation("limit out of range")
    if offset < 0:
        raise err_validation("offset out of range")
    return limit, offset


def list_response(rows, filters=None, serializer=None):
    limit, offset = parse_limit_offset()
    items = list(rows)
    if filters:
        for key, val in filters.items():
            items = [r for r in items if str(r.get(key)) == str(val)]
    items.sort(key=lambda r: (r.get("_created_seq", 0),))
    total = len(items)
    page = items[offset:offset + limit]
    out = [(serializer(r) if serializer else strip_internal(r)) for r in page]
    return ok_list(out, limit, offset, total)


def strip_internal(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def new_common():
    t = now()
    return {
        "id": new_id(),
        "created_at": iso(t),
        "updated_at": iso(t),
        "version": 1,
        "_created_seq": next_seq(),
    }


def touch(res):
    res["updated_at"] = iso(now())
    res["version"] += 1


# ---------------------------------------------------------------------------
# Numeric helpers (Decimal money / units)
# ---------------------------------------------------------------------------
def rhu_int(d):
    """Round half-up to a whole integer, return int."""
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_cents(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def waste_pcts(day):
    produced = day["produced_units"]
    if produced == 0:
        return Decimal("0.0"), Decimal("0.0")
    std = (Decimal(day["discarded_units"]) / Decimal(produced) * Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    net = ((Decimal(day["discarded_units"] - day["donated_units"]) / Decimal(produced))
           * Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return std, net


def recompute_waste(day):
    std, net = waste_pcts(day)
    day["waste_pct_standard"] = float(std)
    day["waste_pct_net"] = float(net)


# ---------------------------------------------------------------------------
# Field-shape validators
# ---------------------------------------------------------------------------
def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise err_validation(f"{field} is required and must be a string")
    return v


def opt_int(data, field):
    if field not in data or data[field] is None:
        return None
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{field} must be an integer")
    return v


def req_int(data, field):
    v = opt_int(data, field)
    if v is None:
        raise err_validation(f"{field} is required and must be an integer")
    return v


def req_bool(data, field, default=None):
    if field not in data or data[field] is None:
        if default is None:
            raise err_validation(f"{field} is required and must be a boolean")
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise err_validation(f"{field} must be a boolean")
    return v


def valid_business_date(value):
    if not isinstance(value, str):
        raise err_validation("business_date must be a string")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        raise err_validation("business_date must be YYYY-MM-DD")
    return value


# ---------------------------------------------------------------------------
# Existence lookups (path left-to-right)
# ---------------------------------------------------------------------------
def get_store_day(day_id):
    sd = db["store_days"].get(day_id)
    if sd is None:
        raise ApiError("ERR_STORE_DAY_NOT_FOUND", 404, "store day not found")
    return sd


def get_daypart(daypart_id):
    dp = db["dayparts"].get(daypart_id)
    if dp is None:
        raise ApiError("ERR_DAYPART_NOT_FOUND", 404, "daypart not found")
    return dp


def get_event(event_id):
    ev = db["demand_events"].get(event_id)
    if ev is None:
        raise ApiError("ERR_EVENT_NOT_FOUND", 404, "demand event not found")
    return ev


def get_dough(batch_id):
    b = db["dough_batches"].get(batch_id)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404, "dough batch not found")
    return b


def get_cheese(batch_id):
    b = db["cheese_batches"].get(batch_id)
    if b is None:
        raise ApiError("ERR_BATCH_NOT_FOUND", 404, "cheese batch not found")
    return b


def get_product(product_id):
    p = db["products"].get(product_id)
    if p is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    return p


def get_run(run_id):
    r = db["production_runs"].get(run_id)
    if r is None:
        raise ApiError("ERR_PRODUCTION_RUN_NOT_FOUND", 404, "production run not found")
    return r


def get_hold_unit(unit_id):
    u = db["hold_units"].get(unit_id)
    if u is None:
        raise ApiError("ERR_HOLD_UNIT_NOT_FOUND", 404, "hold unit not found")
    return u


def get_order(order_id):
    o = db["orders"].get(order_id)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "order not found")
    return o


def get_slot(slot_id):
    s = db["locker_slots"].get(slot_id)
    if s is None:
        raise ApiError("ERR_LOCKER_SLOT_NOT_FOUND", 404, "locker slot not found")
    return s


def get_waste_log(log_id):
    w = db["waste_logs"].get(log_id)
    if w is None:
        raise ApiError("ERR_VALIDATION", 404, "waste log not found")
    return w


def get_shift(shift_id):
    s = db["crew_shifts"].get(shift_id)
    if s is None:
        raise ApiError("ERR_CREW_SHIFT_NOT_FOUND", 404, "crew shift not found")
    return s


# ---------------------------------------------------------------------------
# Serializers (derived fields computed live)
# ---------------------------------------------------------------------------
def daypart_minute_of_day(dt):
    return dt.hour * 60 + dt.minute


def daypart_instants(dp, day):
    base = datetime.strptime(day["business_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = base + timedelta(minutes=dp["window_start_minute"])
    end = base + timedelta(minutes=dp["window_end_minute"])
    return start, end


def event_status(ev):
    if ev["cancelled"]:
        return "CANCELLED"
    t = now()
    if t < ev["_start"]:
        return "SCHEDULED"
    if t <= ev["_end"]:
        return "ACTIVE"
    return "ENDED"


def overlapping_events(day, dp, statuses):
    start, end = daypart_instants(dp, day)
    out = []
    for ev in db["demand_events"].values():
        if ev["store_day_id"] != day["id"]:
            continue
        if ev["cancelled"]:
            continue
        if event_status(ev) not in statuses:
            continue
        # closed-interval overlap: e.start <= dp.end and dp.start <= e.end
        if ev["_start"] <= end and start <= ev["_end"]:
            out.append(ev)
    return out


def forecast_value(day, dp, statuses):
    evs = overlapping_events(day, dp, statuses)
    total = sum(Decimal(str(ev["demand_multiplier"])) for ev in evs)
    m = max(Decimal("1.0"), total) if evs else Decimal("1.0")
    return rhu_int(Decimal(dp["base_demand_units"]) * m)


def compute_provisional(day, dp):
    return forecast_value(day, dp, {"SCHEDULED", "ACTIVE"})


def compute_final(day, dp):
    return forecast_value(day, dp, {"ACTIVE", "ENDED"})


def compute_made_ahead_target(dp):
    scaled = rhu_int(Decimal(dp["forecast_units_provisional"]) * MADE_AHEAD_RATIO)
    clamped = min(dp["rack_capacity"], scaled)
    return max(0, clamped - dp["preorder_reserved_units"])


def recompute_daypart_forecast(dp):
    day = db["store_days"].get(dp["store_day_id"])
    if day is None:
        return
    dp["forecast_units_provisional"] = compute_provisional(day, dp)
    dp["made_ahead_target"] = compute_made_ahead_target(dp)


def recompute_all_daypart_forecasts():
    for dp in db["dayparts"].values():
        if dp["status"] == "CLOSED":
            continue
        before = (dp["forecast_units_provisional"], dp["made_ahead_target"])
        recompute_daypart_forecast(dp)
        if (dp["forecast_units_provisional"], dp["made_ahead_target"]) != before:
            touch(dp)


def posture_of(dp):
    day = db["store_days"].get(dp["store_day_id"])
    if day is None:
        return "NORMAL"
    std = Decimal(str(day["waste_pct_standard"]))
    return "RESTRICTED" if std >= WASTE_TARGET_PCT else "NORMAL"


def product_promo_locked(product_id):
    """True while any OPEN StoreDay has a Daypart with a non-CLOSED run of this product."""
    for run in db["production_runs"].values():
        if run["product_id"] != product_id:
            continue
        if run["status"] == "CLOSED":
            continue
        dp = db["dayparts"].get(run["daypart_id"])
        if dp is None:
            continue
        day = db["store_days"].get(dp["store_day_id"])
        if day is not None and day["status"] == "OPEN":
            return True
    return False


def serialize_store_day(sd):
    return {
        "id": sd["id"],
        "created_at": sd["created_at"],
        "updated_at": sd["updated_at"],
        "version": sd["version"],
        "business_date": sd["business_date"],
        "status": sd["status"],
        "produced_units": sd["produced_units"],
        "sold_units": sd["sold_units"],
        "discarded_units": sd["discarded_units"],
        "donated_units": sd["donated_units"],
        "waste_pct_standard": sd["waste_pct_standard"],
        "waste_pct_net": sd["waste_pct_net"],
    }


def serialize_daypart(dp):
    return {
        "id": dp["id"],
        "created_at": dp["created_at"],
        "updated_at": dp["updated_at"],
        "version": dp["version"],
        "store_day_id": dp["store_day_id"],
        "label": dp["label"],
        "window_start_minute": dp["window_start_minute"],
        "window_end_minute": dp["window_end_minute"],
        "rack_capacity": dp["rack_capacity"],
        "base_demand_units": dp["base_demand_units"],
        "preorder_reserved_units": dp["preorder_reserved_units"],
        "forecast_units_provisional": dp["forecast_units_provisional"],
        "forecast_units_final": dp["forecast_units_final"],
        "made_ahead_target": dp["made_ahead_target"],
        "posture": posture_of(dp),
        "status": dp["status"],
    }


def serialize_event(ev):
    return {
        "id": ev["id"],
        "created_at": ev["created_at"],
        "updated_at": ev["updated_at"],
        "version": ev["version"],
        "store_day_id": ev["store_day_id"],
        "name": ev["name"],
        "window_start_at": iso(ev["_start"]),
        "window_end_at": iso(ev["_end"]),
        "demand_multiplier": ev["demand_multiplier"],
        "cancelled": ev["cancelled"],
        "status": event_status(ev),
    }


def serialize_dough(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "store_day_id": b["store_day_id"],
        "size_units": b["size_units"],
        "remaining_units": b["remaining_units"],
        "status": b["status"],
        "mixing_started_at": iso(b["mixing_started_at"]),
        "proofing_started_at": iso(b["proofing_started_at"]),
        "proofed_at": iso(b["proofed_at"]),
    }


def serialize_cheese(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "store_day_id": b["store_day_id"],
        "size_units": b["size_units"],
        "remaining_units": b["remaining_units"],
        "status": b["status"],
        "prepped_at": iso(b["prepped_at"]),
        "ready_at": iso(b["ready_at"]),
    }


def serialize_product(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "sku": p["sku"],
        "name": p["name"],
        "list_price_cents": p["list_price_cents"],
        "promo_price_cents": p["promo_price_cents"],
        "customization_allowed": p["customization_allowed"],
        "promo_locked": product_promo_locked(p["id"]),
    }


def serialize_run(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "daypart_id": r["daypart_id"],
        "product_id": r["product_id"],
        "dough_batch_id": r["dough_batch_id"],
        "cheese_batch_id": r["cheese_batch_id"],
        "quantity": r["quantity"],
        "status": r["status"],
        "baked_at": iso(r["baked_at"]),
        "racked_at": iso(r["racked_at"]),
        "units_available": r["units_available"],
    }


def serialize_hold_unit(u):
    return {
        "id": u["id"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
        "production_run_id": u["production_run_id"],
        "product_id": u["product_id"],
        "status": u["status"],
        "racked_at": iso(u["racked_at"]),
        "hold_expires_at": iso(u["hold_expires_at"]),
        "allocated_order_id": u["allocated_order_id"],
        "discarded_reason": u["discarded_reason"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "store_day_id": o["store_day_id"],
        "daypart_id": o["daypart_id"],
        "locker_slot_id": o["locker_slot_id"],
        "customer_id": o["customer_id"],
        "kind": o["kind"],
        "lines": o["lines"],
        "subtotal_cents": o["subtotal_cents"],
        "portal_fee_cents": o["portal_fee_cents"],
        "total_cents": o["total_cents"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "made_ahead_units": o["made_ahead_units"],
        "made_to_order_units": o["made_to_order_units"],
        "pickup_code": o["pickup_code"],
        "code_expires_at": iso(o["code_expires_at"]),
        "ready_at": iso(o["ready_at"]),
    }


def serialize_slot(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "store_day_id": s["store_day_id"],
        "slot_number": s["slot_number"],
        "status": s["status"],
        "current_order_id": s["current_order_id"],
        "occupied_at": iso(s["occupied_at"]),
        "cleaning_started_at": iso(s["cleaning_started_at"]),
    }


def serialize_waste_log(w):
    # Immutable audit append: no updated_at, no version.
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "store_day_id": w["store_day_id"],
        "daypart_id": w["daypart_id"],
        "hold_unit_id": w["hold_unit_id"],
        "quantity": w["quantity"],
        "reason": w["reason"],
        "donated": w["donated"],
        "logged_at": w["logged_at"],
    }


def serialize_shift(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "store_day_id": s["store_day_id"],
        "crew_member_id": s["crew_member_id"],
        "station": s["station"],
        "start_minute": s["start_minute"],
        "end_minute": s["end_minute"],
        "status": s["status"],
    }


# ---------------------------------------------------------------------------
# Clock-driven sweeps (PRD §2.4) — also fire lazily on ordinary operations
# ---------------------------------------------------------------------------
def _waste_log_row(store_day_id, daypart_id, hold_unit_id, reason, donated):
    t = now()
    row = {
        "id": new_id(),
        "created_at": iso(t),
        "store_day_id": store_day_id,
        "daypart_id": daypart_id,
        "hold_unit_id": hold_unit_id,
        "quantity": 1,
        "reason": reason,
        "donated": bool(donated),
        "logged_at": iso(t),
        "_created_seq": next_seq(),
    }
    db["waste_logs"][row["id"]] = row
    return row


def _discard_unit(unit, reason, donated):
    """Move a HOLDING (or already-ALLOCATED release-expired) unit to DISCARDED
    with all side effects. Caller ensures state legality."""
    unit["status"] = "DISCARDED"
    unit["discarded_reason"] = reason
    touch(unit)
    run = db["production_runs"].get(unit["production_run_id"])
    daypart_id = None
    if run is not None:
        daypart_id = run["daypart_id"]
        if run["units_available"] > 0:
            run["units_available"] -= 1
            if run["units_available"] == 0 and run["status"] == "HOLDING":
                run["status"] = "CLOSED"
            touch(run)
    day = db["store_days"].get(unit["_store_day_id"])
    if day is not None:
        day["discarded_units"] += 1
        if donated:
            day["donated_units"] += 1
        recompute_waste(day)
        touch(day)
        _waste_log_row(day["id"], daypart_id, unit["id"], reason, donated)


def _sweep_dough_batches():
    t = now()
    for b in db["dough_batches"].values():
        if b["status"] == "PROOFED" and b["proofed_at"] is not None:
            if t >= b["proofed_at"] + timedelta(minutes=PROOF_MAX_MINUTES):
                b["status"] = "EXPIRED"
                touch(b)


def _sweep_hold_units():
    t = now()
    for u in db["hold_units"].values():
        if u["status"] == "HOLDING" and u["hold_expires_at"] is not None:
            if t >= u["hold_expires_at"]:  # inclusive boundary: expired
                _discard_unit(u, "HOLD_EXPIRED", False)


def _sweep_orders_no_show():
    t = now()
    for o in db["orders"].values():
        if o["fulfillment_status"] != "READY":
            continue
        if o["code_expires_at"] is None:
            continue
        if t > o["code_expires_at"]:  # sweep fires strictly after expiry
            _expire_no_show(o)


def _expire_no_show(o):
    o["fulfillment_status"] = "EXPIRED_NO_SHOW"
    if o["payment_status"] == "PAID":
        o["payment_status"] = "REFUNDED"
    total_qty = sum(line["quantity"] for line in o["lines"])
    day = db["store_days"].get(o["store_day_id"])
    for _ in range(total_qty):
        _waste_log_row(o["store_day_id"], o["daypart_id"], None, "NO_SHOW", False)
    if day is not None:
        day["discarded_units"] += total_qty
        recompute_waste(day)
        touch(day)
    # locker slot -> CLEANING
    if o["locker_slot_id"]:
        slot = db["locker_slots"].get(o["locker_slot_id"])
        if slot is not None and slot["status"] == "OCCUPIED":
            slot["status"] = "CLEANING"
            slot["cleaning_started_at"] = now()
            touch(slot)
    touch(o)


def _sweep_locker_slots():
    t = now()
    for s in db["locker_slots"].values():
        if s["status"] == "CLEANING" and s["cleaning_started_at"] is not None:
            if t >= s["cleaning_started_at"] + timedelta(minutes=CLEAN_MINUTES):
                s["status"] = "IDLE"
                s["current_order_id"] = None
                touch(s)


def _sweep_daypart_activation():
    t = now()
    minute = daypart_minute_of_day(t)
    for dp in db["dayparts"].values():
        if dp["status"] != "PLANNED":
            continue
        day = db["store_days"].get(dp["store_day_id"])
        if day is None or day["status"] != "OPEN":
            continue
        if dp["window_start_minute"] <= minute < dp["window_end_minute"]:
            dp["status"] = "ACTIVE"
            touch(dp)
            _ready_paid_preorders(dp)


def _ready_paid_preorders(dp):
    """Each PAID PORTAL_PREORDER (PLACED) promising this daypart is readied as
    if start-preparation and mark-ready fired."""
    for o in list(db["orders"].values()):
        if o["daypart_id"] != dp["id"]:
            continue
        if o["kind"] != "PORTAL_PREORDER":
            continue
        if o["payment_status"] != "PAID":
            continue
        if o["fulfillment_status"] != "PLACED":
            continue
        _do_start_preparation(o, posture_check=False)
        _do_mark_ready(o)


def run_sweeps():
    # Demand-event status is derived on read; nothing to persist.
    recompute_all_daypart_forecasts()
    _sweep_dough_batches()
    _sweep_hold_units()
    _sweep_orders_no_show()
    _sweep_locker_slots()
    _sweep_daypart_activation()


@app.before_request
def _lazy_sweeps():
    run_sweeps()


# ---------------------------------------------------------------------------
# Order domain operations (used by both endpoints and system sweeps)
# ---------------------------------------------------------------------------
def _do_start_preparation(o, posture_check=True):
    dp = db["dayparts"].get(o["daypart_id"])
    if posture_check and dp is not None and posture_of(dp) == "RESTRICTED":
        raise ApiError(
            "ERR_DAYPART_RESTRICTED", 409,
            "daypart posture RESTRICTED gates order preparation",
        )
    t = now()
    made_ahead = 0
    made_to_order = 0
    for line in o["lines"]:
        desired = line["quantity"] - (1 if line.get("customized") else 0)
        pool = []
        for u in db["hold_units"].values():
            if u["status"] != "HOLDING":
                continue
            if u["product_id"] != line["product_id"]:
                continue
            run = db["production_runs"].get(u["production_run_id"])
            if run is None or run["daypart_id"] != o["daypart_id"]:
                continue
            if u["hold_expires_at"] is None or not (t < u["hold_expires_at"]):
                continue  # boundary instant counts as expired
            pool.append(u)
        pool.sort(key=lambda u: (u["racked_at"], u["_created_seq"]))
        take = min(desired, len(pool))
        for u in pool[:take]:
            u["status"] = "ALLOCATED"
            u["allocated_order_id"] = o["id"]
            touch(u)
            run = db["production_runs"].get(u["production_run_id"])
            if run is not None:
                run["units_available"] -= 1
                if run["units_available"] == 0 and run["status"] == "HOLDING":
                    run["status"] = "CLOSED"
                touch(run)
        made_ahead += take
        made_to_order += line["quantity"] - take
    o["made_ahead_units"] = made_ahead
    o["made_to_order_units"] = made_to_order
    o["fulfillment_status"] = "IN_PREPARATION"
    touch(o)


def _mint_pickup_code(store_day_id):
    t = now()
    active_codes = set()
    for o in db["orders"].values():
        if o["store_day_id"] != store_day_id:
            continue
        if o["pickup_code"] is None:
            continue
        if o["code_expires_at"] is not None and o["code_expires_at"] >= t:
            active_codes.add(o["pickup_code"])
    for _ in range(1000):
        code = "%06d" % random.randint(0, 999999)
        if code not in active_codes:
            return code
    # deterministic fallback (pathological collision loop)
    n = 0
    while True:
        code = "%06d" % n
        if code not in active_codes:
            return code
        n += 1


def _do_mark_ready(o):
    t = now()
    if o["kind"] in PORTAL_KINDS:
        idle = [s for s in db["locker_slots"].values()
                if s["store_day_id"] == o["store_day_id"] and s["status"] == "IDLE"]
        if not idle:
            raise ApiError(
                "ERR_NO_LOCKER_AVAILABLE", 409,
                "no IDLE locker slot available in the store day",
            )
        idle.sort(key=lambda s: s["slot_number"])
        slot = idle[0]
        slot["status"] = "OCCUPIED"
        slot["current_order_id"] = o["id"]
        slot["occupied_at"] = t
        touch(slot)
        o["locker_slot_id"] = slot["id"]
        o["pickup_code"] = _mint_pickup_code(o["store_day_id"])
        o["code_expires_at"] = t + timedelta(minutes=CODE_WINDOW_MINUTES)
    o["ready_at"] = t
    # allocated units -> SOLD
    sold = 0
    for u in db["hold_units"].values():
        if u["status"] == "ALLOCATED" and u["allocated_order_id"] == o["id"]:
            u["status"] = "SOLD"
            touch(u)
            sold += 1
    if sold:
        day = db["store_days"].get(o["store_day_id"])
        if day is not None:
            day["sold_units"] += sold
            touch(day)
    o["fulfillment_status"] = "READY"
    touch(o)


# ===========================================================================
# Routes — logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("StoreManager")
    data = body()
    to = data.get("to_iso8601")
    if to is None:
        raise err_validation("to_iso8601 is required")
    dt = parse_dt(to)
    CLOCK.set(dt)
    run_sweeps()
    return ok_object({"current_utc": iso(CLOCK.now())})


# ===========================================================================
# Routes — StoreDay
# ===========================================================================
@app.route("/store-days", methods=["POST"])
def create_store_day():
    require_roles("StoreManager")
    data = body()
    bd = valid_business_date(data.get("business_date"))
    if any(sd["business_date"] == bd for sd in db["store_days"].values()):
        raise ApiError("ERR_DUPLICATE_BUSINESS_DATE", 409, "business_date already exists")
    sd = new_common()
    sd.update({
        "business_date": bd,
        "status": "PLANNING",
        "produced_units": 0,
        "sold_units": 0,
        "discarded_units": 0,
        "donated_units": 0,
        "waste_pct_standard": 0.0,
        "waste_pct_net": 0.0,
    })
    db["store_days"][sd["id"]] = sd
    return ok_object(serialize_store_day(sd), status=201)


@app.route("/store-days", methods=["GET"])
def list_store_days():
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    return list_response(db["store_days"].values(), filters,
                         serializer=serialize_store_day)


@app.route("/store-days/<day_id>", methods=["GET"])
def get_store_day_route(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    return ok_object(serialize_store_day(get_store_day(day_id)))


@app.route("/store-days/<day_id>", methods=["PUT"])
def update_store_day(day_id):
    require_roles("StoreManager")
    sd = get_store_day(day_id)
    data = body()
    # OCC
    if "expected_store_day_version" in data and data["expected_store_day_version"] is not None:
        if data["expected_store_day_version"] != sd["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale store day version")
    if "business_date" in data:
        bd = valid_business_date(data["business_date"])
        if any(o["business_date"] == bd and o["id"] != sd["id"]
               for o in db["store_days"].values()):
            raise ApiError("ERR_DUPLICATE_BUSINESS_DATE", 409, "business_date already exists")
        sd["business_date"] = bd
    touch(sd)
    return ok_object(serialize_store_day(sd))


@app.route("/store-days/<day_id>/open", methods=["POST"])
def open_store_day(day_id):
    require_roles("StoreManager")
    sd = get_store_day(day_id)
    if sd["status"] != "PLANNING":
        raise err_invalid_state("store day is not PLANNING")
    if not any(dp["store_day_id"] == day_id and dp["status"] == "PLANNED"
               for dp in db["dayparts"].values()):
        raise ApiError("ERR_NO_DAYPARTS_DEFINED", 409, "no PLANNED dayparts defined")
    sd["status"] = "OPEN"
    touch(sd)
    _sweep_daypart_activation()
    return ok_object(serialize_store_day(sd))


@app.route("/store-days/<day_id>/close", methods=["POST"])
def close_store_day(day_id):
    require_roles("StoreManager")
    sd = get_store_day(day_id)
    if sd["status"] != "OPEN":
        raise err_invalid_state("store day is not OPEN")
    if any(dp["store_day_id"] == day_id and dp["status"] != "CLOSED"
           for dp in db["dayparts"].values()):
        raise ApiError("ERR_DAYPARTS_STILL_ACTIVE", 409, "dayparts still active")
    if any(s["store_day_id"] == day_id and s["status"] == "OCCUPIED"
           for s in db["locker_slots"].values()):
        raise ApiError("ERR_LOCKER_SLOTS_OCCUPIED", 409, "locker slots occupied")
    sd["status"] = "CLOSED"
    touch(sd)
    # discard all remaining HOLDING units of this day
    for u in list(db["hold_units"].values()):
        if u["status"] == "HOLDING" and u["_store_day_id"] == day_id:
            _discard_unit(u, "HOLD_EXPIRED", False)
    return ok_object(serialize_store_day(sd))


@app.route("/store-days/<day_id>/reconcile", methods=["POST"])
def reconcile_store_day(day_id):
    require_roles("StoreManager")
    sd = get_store_day(day_id)
    if sd["status"] != "CLOSED":
        raise err_invalid_state("store day is not CLOSED")
    recompute_waste(sd)
    sd["status"] = "RECONCILED"
    touch(sd)
    return ok_object(serialize_store_day(sd))


@app.route("/store-days/<day_id>/waste-report", methods=["GET"])
def waste_report(day_id):
    require_roles("StoreManager", "ShiftLead")
    sd = get_store_day(day_id)
    std = Decimal(str(sd["waste_pct_standard"]))
    return ok_object({
        "store_day_id": sd["id"],
        "produced_units": sd["produced_units"],
        "sold_units": sd["sold_units"],
        "discarded_units": sd["discarded_units"],
        "donated_units": sd["donated_units"],
        "waste_pct_standard": sd["waste_pct_standard"],
        "waste_pct_net": sd["waste_pct_net"],
        "waste_target_pct": float(WASTE_TARGET_PCT),
        "target_breached": std >= WASTE_TARGET_PCT,
    })


# ===========================================================================
# Routes — Daypart
# ===========================================================================
def _daypart_window_overlaps(store_day_id, start, end, exclude_id=None):
    for dp in db["dayparts"].values():
        if dp["store_day_id"] != store_day_id:
            continue
        if exclude_id is not None and dp["id"] == exclude_id:
            continue
        # half-open overlap: start < existing.end and existing.start < end
        if start < dp["window_end_minute"] and dp["window_start_minute"] < end:
            return True
    return False


@app.route("/store-days/<day_id>/dayparts", methods=["POST"])
def create_daypart(day_id):
    require_roles("StoreManager")
    sd = get_store_day(day_id)
    data = body()
    label = data.get("label")
    if label not in DAYPART_LABELS:
        raise err_validation("label must be LUNCH, DINNER or LATE_NIGHT")
    ws = req_int(data, "window_start_minute")
    we = req_int(data, "window_end_minute")
    cap = req_int(data, "rack_capacity")
    base = req_int(data, "base_demand_units")
    if ws < 0 or we <= ws:
        raise err_validation("window_start_minute >= 0 and window_end_minute > window_start_minute required")
    if cap < 1:
        raise err_validation("rack_capacity must be >= 1")
    if base < 0:
        raise err_validation("base_demand_units must be >= 0")
    if _daypart_window_overlaps(day_id, ws, we):
        raise ApiError("ERR_DAYPART_WINDOW_OVERLAP", 409, "daypart window overlaps existing")
    dp = new_common()
    dp.update({
        "store_day_id": day_id,
        "label": label,
        "window_start_minute": ws,
        "window_end_minute": we,
        "rack_capacity": cap,
        "base_demand_units": base,
        "preorder_reserved_units": 0,
        "forecast_units_provisional": 0,
        "forecast_units_final": None,
        "made_ahead_target": 0,
        "status": "PLANNED",
    })
    db["dayparts"][dp["id"]] = dp
    recompute_daypart_forecast(dp)
    return ok_object(serialize_daypart(dp), status=201)


@app.route("/store-days/<day_id>/dayparts", methods=["GET"])
def list_dayparts_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    get_store_day(day_id)
    return list_response([d for d in db["dayparts"].values()
                          if d["store_day_id"] == day_id],
                         serializer=serialize_daypart)


@app.route("/dayparts", methods=["GET"])
def list_dayparts_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    filters = {}
    for k in ("store_day_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["dayparts"].values(), filters,
                         serializer=serialize_daypart)


@app.route("/dayparts/<daypart_id>", methods=["GET"])
def get_daypart_route(daypart_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    return ok_object(serialize_daypart(get_daypart(daypart_id)))


@app.route("/dayparts/<daypart_id>", methods=["PUT"])
def update_daypart(daypart_id):
    require_roles("StoreManager")
    dp = get_daypart(daypart_id)
    data = body()
    if dp["status"] != "PLANNED":
        raise err_invalid_state("only a PLANNED daypart may be updated")
    if "expected_daypart_version" in data and data["expected_daypart_version"] is not None:
        if data["expected_daypart_version"] != dp["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale daypart version")
    new_ws = dp["window_start_minute"]
    new_we = dp["window_end_minute"]
    if "window_start_minute" in data and data["window_start_minute"] is not None:
        new_ws = req_int(data, "window_start_minute")
    if "window_end_minute" in data and data["window_end_minute"] is not None:
        new_we = req_int(data, "window_end_minute")
    if new_ws < 0 or new_we <= new_ws:
        raise err_validation("window_start_minute >= 0 and window_end_minute > window_start_minute required")
    if "rack_capacity" in data and data["rack_capacity"] is not None:
        cap = req_int(data, "rack_capacity")
        if cap < 1:
            raise err_validation("rack_capacity must be >= 1")
        dp["rack_capacity"] = cap
    if "base_demand_units" in data and data["base_demand_units"] is not None:
        base = req_int(data, "base_demand_units")
        if base < 0:
            raise err_validation("base_demand_units must be >= 0")
        dp["base_demand_units"] = base
    if _daypart_window_overlaps(dp["store_day_id"], new_ws, new_we, exclude_id=dp["id"]):
        raise ApiError("ERR_DAYPART_WINDOW_OVERLAP", 409, "daypart window overlaps existing")
    dp["window_start_minute"] = new_ws
    dp["window_end_minute"] = new_we
    recompute_daypart_forecast(dp)
    touch(dp)
    return ok_object(serialize_daypart(dp))


@app.route("/dayparts/<daypart_id>/close", methods=["POST"])
def close_daypart(daypart_id):
    require_roles("ShiftLead")
    dp = get_daypart(daypart_id)
    if dp["status"] != "ACTIVE":
        raise err_invalid_state("daypart is not ACTIVE")
    if any(r["daypart_id"] == daypart_id and r["status"] == "BAKING"
           for r in db["production_runs"].values()):
        raise ApiError("ERR_RUNS_IN_PROGRESS", 409, "production runs in progress")
    day = db["store_days"].get(dp["store_day_id"])
    dp["forecast_units_final"] = compute_final(day, dp)
    dp["status"] = "CLOSED"
    touch(dp)
    # discard every HOLDING unit of this daypart
    for u in list(db["hold_units"].values()):
        if u["status"] != "HOLDING":
            continue
        run = db["production_runs"].get(u["production_run_id"])
        if run is not None and run["daypart_id"] == daypart_id:
            _discard_unit(u, "HOLD_EXPIRED", False)
    # outstanding PAID preorders -> EXPIRED_NO_SHOW + REFUNDED
    for o in list(db["orders"].values()):
        if o["daypart_id"] != daypart_id:
            continue
        if o["kind"] != "PORTAL_PREORDER":
            continue
        if o["payment_status"] != "PAID":
            continue
        if o["fulfillment_status"] in ("READY", "PICKED_UP"):
            continue
        o["fulfillment_status"] = "EXPIRED_NO_SHOW"
        o["payment_status"] = "REFUNDED"
        if o["locker_slot_id"]:
            slot = db["locker_slots"].get(o["locker_slot_id"])
            if slot is not None and slot["status"] == "OCCUPIED":
                slot["status"] = "CLEANING"
                slot["cleaning_started_at"] = now()
                touch(slot)
        touch(o)
    return ok_object(serialize_daypart(dp))


# ===========================================================================
# Routes — DemandEvent
# ===========================================================================
@app.route("/store-days/<day_id>/demand-events", methods=["POST"])
def create_demand_event(day_id):
    require_roles("StoreManager")
    get_store_day(day_id)
    data = body()
    name = req_str(data, "name")
    ws = parse_dt(data.get("window_start_at"))
    we = parse_dt(data.get("window_end_at"))
    mult = data.get("demand_multiplier")
    if isinstance(mult, bool) or not isinstance(mult, (int, float)):
        raise err_validation("demand_multiplier must be a number")
    if we < ws:
        raise err_validation("window_end_at must be >= window_start_at")
    if mult <= 0:
        raise err_validation("demand_multiplier must be > 0")
    for ev in db["demand_events"].values():
        if ev["store_day_id"] != day_id or ev["cancelled"]:
            continue
        # closed-interval intersection; adjacency intersects
        if ev["_start"] <= we and ws <= ev["_end"]:
            raise ApiError("ERR_EVENT_WINDOW_OVERLAP", 409, "event window overlaps existing")
    ev = new_common()
    ev.update({
        "store_day_id": day_id,
        "name": name,
        "demand_multiplier": mult,
        "cancelled": False,
        "_start": ws,
        "_end": we,
    })
    db["demand_events"][ev["id"]] = ev
    _recompute_overlapping_dayparts(day_id, ws, we)
    return ok_object(serialize_event(ev), status=201)


def _recompute_overlapping_dayparts(store_day_id, ev_start, ev_end):
    day = db["store_days"].get(store_day_id)
    if day is None:
        return
    for dp in db["dayparts"].values():
        if dp["store_day_id"] != store_day_id:
            continue
        if dp["status"] not in ("PLANNED", "ACTIVE"):
            continue
        start, end = daypart_instants(dp, day)
        if ev_start <= end and start <= ev_end:
            recompute_daypart_forecast(dp)
            touch(dp)


@app.route("/store-days/<day_id>/demand-events", methods=["GET"])
def list_demand_events_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_store_day(day_id)
    return list_response([e for e in db["demand_events"].values()
                          if e["store_day_id"] == day_id],
                         serializer=serialize_event)


@app.route("/demand-events", methods=["GET"])
def list_demand_events_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    if request.args.get("store_day_id") is not None:
        filters["store_day_id"] = request.args.get("store_day_id")
    return list_response(db["demand_events"].values(), filters,
                         serializer=serialize_event)


@app.route("/demand-events/<event_id>", methods=["GET"])
def get_demand_event_route(event_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_event(get_event(event_id)))


@app.route("/demand-events/<event_id>/cancel", methods=["POST"])
def cancel_demand_event(event_id):
    require_roles("StoreManager")
    ev = get_event(event_id)
    if event_status(ev) != "SCHEDULED":
        raise ApiError("ERR_EVENT_NOT_CANCELLABLE", 409, "only SCHEDULED events may be cancelled")
    ev["cancelled"] = True
    touch(ev)
    _recompute_overlapping_dayparts(ev["store_day_id"], ev["_start"], ev["_end"])
    return ok_object(serialize_event(ev))


# ===========================================================================
# Routes — DoughBatch / CheeseBatch
# ===========================================================================
@app.route("/store-days/<day_id>/dough-batches", methods=["POST"])
def create_dough_batch(day_id):
    require_roles("CrewMember")
    get_store_day(day_id)
    data = body()
    size = req_int(data, "size_units")
    if size < 1:
        raise err_validation("size_units must be >= 1")
    b = new_common()
    b.update({
        "store_day_id": day_id,
        "size_units": size,
        "remaining_units": size,
        "status": "MIXING",
        "mixing_started_at": now(),
        "proofing_started_at": None,
        "proofed_at": None,
    })
    db["dough_batches"][b["id"]] = b
    return ok_object(serialize_dough(b), status=201)


@app.route("/dough-batches/<batch_id>", methods=["GET"])
def get_dough_route(batch_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_dough(get_dough(batch_id)))


@app.route("/store-days/<day_id>/dough-batches", methods=["GET"])
def list_dough_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_store_day(day_id)
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    return list_response([b for b in db["dough_batches"].values()
                          if b["store_day_id"] == day_id], filters,
                         serializer=serialize_dough)


@app.route("/dough-batches", methods=["GET"])
def list_dough_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("store_day_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["dough_batches"].values(), filters,
                         serializer=serialize_dough)


@app.route("/dough-batches/<batch_id>/advance", methods=["POST"])
def advance_dough(batch_id):
    require_roles("CrewMember")
    b = get_dough(batch_id)
    t = now()
    if b["status"] == "MIXING":
        b["status"] = "PROOFING"
        b["proofing_started_at"] = t
        touch(b)
    elif b["status"] == "PROOFING":
        if t < b["proofing_started_at"] + timedelta(minutes=PROOF_MIN_MINUTES):
            raise ApiError("ERR_PROOF_NOT_READY", 409, "proofing floor not reached")
        b["status"] = "PROOFED"
        b["proofed_at"] = t
        touch(b)
    else:
        raise ApiError("ERR_BATCH_STATE", 409, "no forward transition from this state")
    return ok_object(serialize_dough(b))


@app.route("/store-days/<day_id>/cheese-batches", methods=["POST"])
def create_cheese_batch(day_id):
    require_roles("CrewMember")
    get_store_day(day_id)
    data = body()
    size = req_int(data, "size_units")
    if size < 1:
        raise err_validation("size_units must be >= 1")
    b = new_common()
    b.update({
        "store_day_id": day_id,
        "size_units": size,
        "remaining_units": size,
        "status": "PREPPING",
        "prepped_at": now(),
        "ready_at": None,
    })
    db["cheese_batches"][b["id"]] = b
    return ok_object(serialize_cheese(b), status=201)


@app.route("/cheese-batches/<batch_id>", methods=["GET"])
def get_cheese_route(batch_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_cheese(get_cheese(batch_id)))


@app.route("/store-days/<day_id>/cheese-batches", methods=["GET"])
def list_cheese_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_store_day(day_id)
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    return list_response([b for b in db["cheese_batches"].values()
                          if b["store_day_id"] == day_id], filters,
                         serializer=serialize_cheese)


@app.route("/cheese-batches", methods=["GET"])
def list_cheese_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("store_day_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["cheese_batches"].values(), filters,
                         serializer=serialize_cheese)


@app.route("/cheese-batches/<batch_id>/advance", methods=["POST"])
def advance_cheese(batch_id):
    require_roles("CrewMember")
    b = get_cheese(batch_id)
    t = now()
    if b["status"] == "PREPPING":
        b["status"] = "RESTING"
        touch(b)
    elif b["status"] == "RESTING":
        if t < b["prepped_at"] + timedelta(minutes=CHEESE_REST_MINUTES):
            raise ApiError("ERR_CHEESE_NOT_READY", 409, "cheese rest floor not reached")
        b["status"] = "READY"
        b["ready_at"] = t
        touch(b)
    else:
        raise ApiError("ERR_BATCH_STATE", 409, "no forward transition from this state")
    return ok_object(serialize_cheese(b))


# ===========================================================================
# Routes — Product
# ===========================================================================
@app.route("/products", methods=["POST"])
def create_product():
    require_roles("StoreManager")
    data = body()
    sku = req_str(data, "sku")
    name = req_str(data, "name")
    price = req_int(data, "list_price_cents")
    if price < 1:
        raise err_validation("list_price_cents must be >= 1")
    promo = data.get("promo_price_cents")
    if promo is not None:
        if isinstance(promo, bool) or not isinstance(promo, int):
            raise err_validation("promo_price_cents must be an integer")
        if promo >= price:
            raise ApiError("ERR_PROMO_PRICE_INVALID", 422, "promo price must be below list price")
    customization = req_bool(data, "customization_allowed", default=False)
    if any(p["sku"] == sku for p in db["products"].values()):
        raise ApiError("ERR_DUPLICATE_SKU", 409, "sku already exists")
    p = new_common()
    p.update({
        "sku": sku,
        "name": name,
        "list_price_cents": price,
        "promo_price_cents": promo,
        "customization_allowed": customization,
    })
    db["products"][p["id"]] = p
    return ok_object(serialize_product(p), status=201)


@app.route("/products", methods=["GET"])
def list_products():
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    return list_response(db["products"].values(), serializer=serialize_product)


@app.route("/products/<product_id>", methods=["GET"])
def get_product_route(product_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    return ok_object(serialize_product(get_product(product_id)))


@app.route("/products/<product_id>", methods=["PUT"])
def update_product(product_id):
    require_roles("StoreManager")
    p = get_product(product_id)
    data = body()
    promo_touched = ("promo_price_cents" in data and
                     data["promo_price_cents"] != p["promo_price_cents"])
    new_price = p["list_price_cents"]
    new_promo = p["promo_price_cents"]
    if "list_price_cents" in data and data["list_price_cents"] is not None:
        new_price = req_int(data, "list_price_cents")
        if new_price < 1:
            raise err_validation("list_price_cents must be >= 1")
    if "promo_price_cents" in data:
        new_promo = data["promo_price_cents"]
        if new_promo is not None:
            if isinstance(new_promo, bool) or not isinstance(new_promo, int):
                raise err_validation("promo_price_cents must be an integer")
    if new_promo is not None and new_promo >= new_price:
        raise ApiError("ERR_PROMO_PRICE_INVALID", 422, "promo price must be below list price")
    if promo_touched and product_promo_locked(product_id):
        raise ApiError("ERR_PROMO_PRICE_LOCKED", 409, "promo price locked by live production")
    if "name" in data and data["name"] is not None:
        p["name"] = req_str(data, "name")
    if "customization_allowed" in data and data["customization_allowed"] is not None:
        p["customization_allowed"] = req_bool(data, "customization_allowed")
    p["list_price_cents"] = new_price
    p["promo_price_cents"] = new_promo
    touch(p)
    return ok_object(serialize_product(p))


# ===========================================================================
# Routes — ProductionRun
# ===========================================================================
@app.route("/dayparts/<daypart_id>/production-runs", methods=["POST"])
def create_production_run(daypart_id):
    require_roles("ShiftLead")
    get_daypart(daypart_id)
    data = body()
    product = get_product(req_str(data, "product_id"))
    dough = get_dough(req_str(data, "dough_batch_id"))
    cheese = get_cheese(req_str(data, "cheese_batch_id"))
    qty = req_int(data, "quantity")
    if qty < 1:
        raise err_validation("quantity must be >= 1")
    r = new_common()
    r.update({
        "daypart_id": daypart_id,
        "product_id": product["id"],
        "dough_batch_id": dough["id"],
        "cheese_batch_id": cheese["id"],
        "quantity": qty,
        "status": "PLANNED",
        "baked_at": None,
        "racked_at": None,
        "units_available": 0,
    })
    db["production_runs"][r["id"]] = r
    return ok_object(serialize_run(r), status=201)


@app.route("/dayparts/<daypart_id>/production-runs", methods=["GET"])
def list_runs_of(daypart_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_daypart(daypart_id)
    return list_response([r for r in db["production_runs"].values()
                          if r["daypart_id"] == daypart_id],
                         serializer=serialize_run)


@app.route("/production-runs", methods=["GET"])
def list_runs_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("daypart_id", "product_id", "dough_batch_id", "cheese_batch_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["production_runs"].values(), filters,
                         serializer=serialize_run)


@app.route("/production-runs/<run_id>", methods=["GET"])
def get_run_route(run_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_run(get_run(run_id)))


@app.route("/production-runs/<run_id>/start-baking", methods=["POST"])
def start_baking(run_id):
    require_roles("CrewMember")
    r = get_run(run_id)
    if r["status"] != "PLANNED":
        raise err_invalid_state("run is not PLANNED")
    dp = get_daypart(r["daypart_id"])
    if dp["status"] != "ACTIVE":
        raise ApiError("ERR_DAYPART_NOT_ACTIVE", 409, "daypart is not ACTIVE")
    dough = db["dough_batches"].get(r["dough_batch_id"])
    if dough is None or dough["status"] != "PROOFED" or dough["remaining_units"] < r["quantity"]:
        raise ApiError("ERR_DOUGH_UNAVAILABLE", 409, "dough batch not PROOFED or insufficient")
    cheese = db["cheese_batches"].get(r["cheese_batch_id"])
    if cheese is None or cheese["status"] != "READY" or cheese["remaining_units"] < r["quantity"]:
        raise ApiError("ERR_CHEESE_UNAVAILABLE", 409, "cheese batch not READY or insufficient")
    dough["remaining_units"] -= r["quantity"]
    if dough["remaining_units"] == 0:
        dough["status"] = "DEPLETED"
    touch(dough)
    cheese["remaining_units"] -= r["quantity"]
    if cheese["remaining_units"] == 0:
        cheese["status"] = "DEPLETED"
    touch(cheese)
    r["baked_at"] = now()
    r["status"] = "BAKING"
    touch(r)
    return ok_object(serialize_run(r))


@app.route("/production-runs/<run_id>/rack", methods=["POST"])
def rack_run(run_id):
    require_roles("CrewMember")
    r = get_run(run_id)
    if r["status"] != "BAKING":
        raise err_invalid_state("run is not BAKING")
    dp = get_daypart(r["daypart_id"])
    if dp["status"] != "ACTIVE":
        raise ApiError("ERR_DAYPART_NOT_ACTIVE", 409, "daypart is not ACTIVE")
    occupancy = sum(
        1 for u in db["hold_units"].values()
        if u["status"] in ("HOLDING", "ALLOCATED")
        and db["production_runs"].get(u["production_run_id"]) is not None
        and db["production_runs"][u["production_run_id"]]["daypart_id"] == r["daypart_id"]
    )
    if occupancy + r["quantity"] > dp["rack_capacity"]:
        raise ApiError("ERR_RACK_CAPACITY_EXCEEDED", 409, "rack capacity exceeded")
    t = now()
    run_day = db["dayparts"].get(r["daypart_id"])
    store_day_id = run_day["store_day_id"] if run_day else None
    for _ in range(r["quantity"]):
        u = new_common()
        u.update({
            "production_run_id": r["id"],
            "product_id": r["product_id"],
            "status": "HOLDING",
            "racked_at": t,
            "hold_expires_at": t + timedelta(minutes=HOLD_MINUTES),
            "allocated_order_id": None,
            "discarded_reason": None,
            "_store_day_id": store_day_id,
        })
        db["hold_units"][u["id"]] = u
    r["units_available"] = r["quantity"]
    r["racked_at"] = t
    r["status"] = "HOLDING"
    touch(r)
    day = db["store_days"].get(store_day_id)
    if day is not None:
        day["produced_units"] += r["quantity"]
        recompute_waste(day)
        touch(day)
    return ok_object(serialize_run(r))


# ===========================================================================
# Routes — HoldUnit
# ===========================================================================
@app.route("/hold-units", methods=["GET"])
def list_hold_units():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("production_run_id", "status", "product_id", "allocated_order_id"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["hold_units"].values(), filters,
                         serializer=serialize_hold_unit)


@app.route("/hold-units/<unit_id>", methods=["GET"])
def get_hold_unit_route(unit_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_hold_unit(get_hold_unit(unit_id)))


@app.route("/hold-units/<unit_id>/discard", methods=["POST"])
def discard_hold_unit(unit_id):
    require_roles("ShiftLead")
    u = get_hold_unit(unit_id)
    data = body()
    reason = data.get("reason")
    if reason not in MANUAL_DISCARD_REASONS:
        raise ApiError("ERR_INVALID_DISCARD_REASON", 400,
                       "reason must be DAMAGED or QUALITY")
    if u["status"] != "HOLDING":
        raise err_invalid_state("hold unit is not HOLDING")
    donated = req_bool(data, "donated", default=False)
    _discard_unit(u, reason, donated)
    return ok_object(serialize_hold_unit(u))


# ===========================================================================
# Routes — Order
# ===========================================================================
@app.route("/orders", methods=["POST"])
def create_order():
    uid, role = get_auth()
    if role not in ("Customer", "ShiftLead"):
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    data = body()
    store_day_id = data.get("store_day_id")
    daypart_id = data.get("daypart_id")
    sd = get_store_day(store_day_id)
    dp = get_daypart(daypart_id)
    customer_id = req_str(data, "customer_id")
    kind = data.get("kind")
    if kind not in ORDER_KINDS:
        raise err_validation("kind must be PORTAL_STANDARD, PORTAL_PREORDER or COUNTER")
    # kind-vs-role matrix
    if kind == "COUNTER":
        if role != "ShiftLead":
            raise ApiError("ERR_UNAUTHORIZED", 403, "COUNTER orders are placed by ShiftLead")
    else:
        if role != "Customer":
            raise ApiError("ERR_UNAUTHORIZED", 403, "portal orders are placed by Customer")
        if uid != customer_id:
            raise ApiError("ERR_UNAUTHORIZED", 403, "customer must place orders for itself")
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        raise err_validation("lines must be a non-empty array")
    # resolve products (existence before business rules)
    resolved = []
    for line in lines:
        if not isinstance(line, dict):
            raise err_validation("each line must be an object")
        pid = line.get("product_id")
        if not isinstance(pid, str) or not pid:
            raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
        product = get_product(pid)
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise err_validation("line quantity must be >= 1")
        customized = line.get("customized", False)
        if not isinstance(customized, bool):
            raise err_validation("customized must be a boolean")
        resolved.append((product, qty, customized))
    # customization permission before daypart-status rule
    for product, qty, customized in resolved:
        if customized and not product["customization_allowed"]:
            raise ApiError("ERR_CUSTOMIZATION_NOT_ALLOWED", 422,
                           "product does not allow customization")
    if kind == "PORTAL_PREORDER":
        if dp["status"] != "PLANNED":
            raise ApiError("ERR_PREORDER_DAYPART_NOT_PLANNED", 409,
                           "preorder requires PLANNED daypart")
    else:
        if dp["status"] != "ACTIVE":
            raise ApiError("ERR_DAYPART_NOT_ACTIVE", 409, "daypart is not ACTIVE")
    # pricing: per-line rounding pinned before summation
    subtotal = 0
    fee = 0
    line_rows = []
    for product, qty, customized in resolved:
        if product["promo_price_cents"] is not None and not customized:
            unit_price = product["promo_price_cents"]
        else:
            unit_price = product["list_price_cents"]
        line_sub = unit_price * qty
        subtotal += line_sub
        if kind in PORTAL_KINDS:
            fee += rhu_cents(Decimal(line_sub) * PORTAL_FEE_RATE)
        line_rows.append({
            "product_id": product["id"],
            "quantity": qty,
            "customized": customized,
        })
    o = new_common()
    o.update({
        "store_day_id": sd["id"],
        "daypart_id": dp["id"],
        "locker_slot_id": None,
        "customer_id": customer_id,
        "kind": kind,
        "lines": line_rows,
        "subtotal_cents": subtotal,
        "portal_fee_cents": fee,
        "total_cents": subtotal + fee,
        "payment_status": "UNPAID",
        "fulfillment_status": "PLACED",
        "made_ahead_units": 0,
        "made_to_order_units": 0,
        "pickup_code": None,
        "code_expires_at": None,
        "ready_at": None,
    })
    db["orders"][o["id"]] = o
    return ok_object(serialize_order(o), status=201)


@app.route("/orders", methods=["GET"])
def list_orders():
    require_roles("StoreManager", "ShiftLead", "CrewMember", "Customer")
    filters = {}
    for k in ("store_day_id", "daypart_id", "customer_id", "kind",
              "fulfillment_status", "locker_slot_id"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["orders"].values(), filters,
                         serializer=serialize_order)


@app.route("/orders/<order_id>", methods=["GET"])
def get_order_route(order_id):
    uid, role = get_auth()
    o = get_order(order_id)
    if role == "Customer" and uid != o["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer does not own this order")
    return ok_object(serialize_order(o))


@app.route("/orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    uid, role = get_auth()
    if role != "Customer":
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    o = get_order(order_id)
    if uid != o["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer does not own this order")
    if o["payment_status"] != "UNPAID":
        raise err_invalid_state("order is not UNPAID")
    if o["fulfillment_status"] != "PLACED":
        raise err_invalid_state("order fulfillment is not PLACED")
    o["payment_status"] = "PAID"
    touch(o)
    if o["kind"] == "PORTAL_PREORDER":
        dp = db["dayparts"].get(o["daypart_id"])
        if dp is not None and dp["status"] == "PLANNED":
            total_qty = sum(line["quantity"] for line in o["lines"])
            dp["preorder_reserved_units"] += total_qty
            recompute_daypart_forecast(dp)
            touch(dp)
    return ok_object(serialize_order(o))


@app.route("/orders/<order_id>/start-preparation", methods=["POST"])
def start_preparation(order_id):
    require_roles("CrewMember")
    o = get_order(order_id)
    if o["fulfillment_status"] != "PLACED":
        raise err_invalid_state("order is not PLACED")
    dp = db["dayparts"].get(o["daypart_id"])
    if o["kind"] == "PORTAL_PREORDER":
        if dp is None or dp["status"] != "ACTIVE":
            raise ApiError("ERR_PREORDER_DAYPART_NOT_ACTIVE", 409,
                           "preorder requires promised daypart ACTIVE")
    if o["payment_status"] != "PAID" and o["kind"] != "COUNTER":
        raise ApiError("ERR_ORDER_NOT_PAID", 409, "order is not PAID")
    _do_start_preparation(o, posture_check=True)
    return ok_object(serialize_order(o))


@app.route("/orders/<order_id>/mark-ready", methods=["POST"])
def mark_ready(order_id):
    require_roles("CrewMember")
    o = get_order(order_id)
    if o["fulfillment_status"] != "IN_PREPARATION":
        raise err_invalid_state("order is not IN_PREPARATION")
    _do_mark_ready(o)
    return ok_object(serialize_order(o))


@app.route("/orders/<order_id>/claim", methods=["POST"])
def claim_order(order_id):
    uid, role = get_auth()
    if role != "Customer":
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    o = get_order(order_id)
    if uid != o["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer does not own this order")
    if o["kind"] not in PORTAL_KINDS:
        raise ApiError("ERR_NOT_PORTAL_ORDER", 409, "not a portal order")
    if o["fulfillment_status"] != "READY":
        raise err_invalid_state("order is not READY")
    data = body()
    code = data.get("pickup_code")
    if code != o["pickup_code"]:
        raise ApiError("ERR_PICKUP_CODE_INVALID", 409, "pickup code does not match")
    if now() > o["code_expires_at"]:  # boundary itself remains valid
        raise ApiError("ERR_PICKUP_CODE_EXPIRED", 409, "pickup code expired")
    o["fulfillment_status"] = "PICKED_UP"
    touch(o)
    if o["locker_slot_id"]:
        slot = db["locker_slots"].get(o["locker_slot_id"])
        if slot is not None and slot["status"] == "OCCUPIED":
            slot["status"] = "CLEANING"
            slot["cleaning_started_at"] = now()
            touch(slot)
    return ok_object(serialize_order(o))


@app.route("/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    uid, role = get_auth()
    if role != "Customer":
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    o = get_order(order_id)
    if uid != o["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403, "customer does not own this order")
    if o["fulfillment_status"] not in ("PLACED", "IN_PREPARATION"):
        raise err_invalid_state("order cannot be cancelled from this state")
    had_paid_reservation = (
        o["kind"] == "PORTAL_PREORDER" and o["payment_status"] == "PAID"
    )
    if o["payment_status"] == "PAID":
        o["payment_status"] = "REFUNDED"
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    if had_paid_reservation:
        dp = db["dayparts"].get(o["daypart_id"])
        if dp is not None:
            total_qty = sum(line["quantity"] for line in o["lines"])
            dp["preorder_reserved_units"] = max(
                0, dp["preorder_reserved_units"] - total_qty
            )
            recompute_daypart_forecast(dp)
            touch(dp)
    # release allocated hold units
    t = now()
    for u in db["hold_units"].values():
        if u["status"] != "ALLOCATED" or u["allocated_order_id"] != o["id"]:
            continue
        if u["hold_expires_at"] is not None and t >= u["hold_expires_at"]:
            u["allocated_order_id"] = None
            _discard_unit(u, "HOLD_EXPIRED", False)
        else:
            u["status"] = "HOLDING"
            u["allocated_order_id"] = None
            touch(u)
            run = db["production_runs"].get(u["production_run_id"])
            if run is not None:
                run["units_available"] += 1
                touch(run)  # a CLOSED run stays CLOSED
    return ok_object(serialize_order(o))


# ===========================================================================
# Routes — LockerSlot
# ===========================================================================
@app.route("/store-days/<day_id>/locker-slots", methods=["POST"])
def create_locker_slot(day_id):
    require_roles("StoreManager")
    get_store_day(day_id)
    data = body()
    slot_number = req_int(data, "slot_number")
    if slot_number < 1:
        raise err_validation("slot_number must be >= 1")
    if any(s["store_day_id"] == day_id and s["slot_number"] == slot_number
           for s in db["locker_slots"].values()):
        raise ApiError("ERR_DUPLICATE_SLOT_NUMBER", 409,
                       "slot_number already exists for the store day")
    s = new_common()
    s.update({
        "store_day_id": day_id,
        "slot_number": slot_number,
        "status": "IDLE",
        "current_order_id": None,
        "occupied_at": None,
        "cleaning_started_at": None,
    })
    db["locker_slots"][s["id"]] = s
    return ok_object(serialize_slot(s), status=201)


@app.route("/store-days/<day_id>/locker-slots", methods=["GET"])
def list_slots_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_store_day(day_id)
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = request.args.get("status")
    return list_response([s for s in db["locker_slots"].values()
                          if s["store_day_id"] == day_id], filters,
                         serializer=serialize_slot)


@app.route("/locker-slots", methods=["GET"])
def list_slots_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("store_day_id", "current_order_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["locker_slots"].values(), filters,
                         serializer=serialize_slot)


@app.route("/locker-slots/<slot_id>", methods=["GET"])
def get_slot_route(slot_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_slot(get_slot(slot_id)))


# ===========================================================================
# Routes — WasteLog
# ===========================================================================
@app.route("/store-days/<day_id>/waste-logs", methods=["GET"])
def list_waste_logs_of(day_id):
    require_roles("StoreManager", "ShiftLead")
    get_store_day(day_id)
    filters = {}
    if request.args.get("reason") is not None:
        filters["reason"] = request.args.get("reason")
    return list_response([w for w in db["waste_logs"].values()
                          if w["store_day_id"] == day_id], filters,
                         serializer=serialize_waste_log)


@app.route("/waste-logs", methods=["GET"])
def list_waste_logs_flat():
    require_roles("StoreManager", "ShiftLead")
    filters = {}
    for k in ("store_day_id", "daypart_id", "hold_unit_id", "reason"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["waste_logs"].values(), filters,
                         serializer=serialize_waste_log)


@app.route("/waste-logs/<log_id>", methods=["GET"])
def get_waste_log_route(log_id):
    require_roles("StoreManager", "ShiftLead")
    return ok_object(serialize_waste_log(get_waste_log(log_id)))


# ===========================================================================
# Routes — CrewShift
# ===========================================================================
@app.route("/store-days/<day_id>/crew-shifts", methods=["POST"])
def create_crew_shift(day_id):
    require_roles("ShiftLead")
    get_store_day(day_id)
    data = body()
    crew_member_id = req_str(data, "crew_member_id")
    station = data.get("station")
    if station not in STATIONS:
        raise err_validation("station must be OVEN, CUT_TABLE, LOCKER_BAY or DOUGH_PREP")
    start = req_int(data, "start_minute")
    end = req_int(data, "end_minute")
    if start < 0 or end <= start:
        raise err_validation("start_minute >= 0 and end_minute > start_minute required")
    for s in db["crew_shifts"].values():
        if s["store_day_id"] != day_id or s["status"] != "SCHEDULED":
            continue
        half_open_overlap = (start < s["end_minute"] and s["start_minute"] < end)
        if not half_open_overlap:
            continue
        if s["crew_member_id"] == crew_member_id or s["station"] == station:
            raise ApiError("ERR_SHIFT_CONFLICT", 409, "crew shift conflict")
    s = new_common()
    s.update({
        "store_day_id": day_id,
        "crew_member_id": crew_member_id,
        "station": station,
        "start_minute": start,
        "end_minute": end,
        "status": "SCHEDULED",
    })
    db["crew_shifts"][s["id"]] = s
    return ok_object(serialize_shift(s), status=201)


@app.route("/store-days/<day_id>/crew-shifts", methods=["GET"])
def list_shifts_of(day_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    get_store_day(day_id)
    filters = {}
    for k in ("crew_member_id", "station"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response([s for s in db["crew_shifts"].values()
                          if s["store_day_id"] == day_id], filters,
                         serializer=serialize_shift)


@app.route("/crew-shifts", methods=["GET"])
def list_shifts_flat():
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    filters = {}
    for k in ("store_day_id", "crew_member_id", "station", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args.get(k)
    return list_response(db["crew_shifts"].values(), filters,
                         serializer=serialize_shift)


@app.route("/crew-shifts/<shift_id>", methods=["GET"])
def get_shift_route(shift_id):
    require_roles("StoreManager", "ShiftLead", "CrewMember")
    return ok_object(serialize_shift(get_shift(shift_id)))


@app.route("/crew-shifts/<shift_id>/end", methods=["POST"])
def end_crew_shift(shift_id):
    require_roles("ShiftLead")
    s = get_shift(shift_id)
    if s["status"] != "SCHEDULED":
        raise err_invalid_state("crew shift is not SCHEDULED")
    s["status"] = "ENDED"
    touch(s)
    return ok_object(serialize_shift(s))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
