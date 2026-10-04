"""Core utilities: logical clock, timestamps, errors, response envelope,
auth, store, pagination, helpers. All shared state lives here (in-memory)."""
import os
import re
import uuid
import random
import string
import threading
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Logical clock (never falls back to wall-clock)
# ---------------------------------------------------------------------------

_lock = threading.RLock()

_logical_now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now():
    with _lock:
        return _logical_now


def set_logical_now(dt):
    global _logical_now
    with _lock:
        _logical_now = dt


def parse_iso(value):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime value", 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime value", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return iso_z(dt)


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def ok_obj(data, code=200):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": wall_now_iso()},
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": wall_now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_resp(error_id, message, http_status):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": wall_now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = {"Anonymous", "Customer", "Technician", "CustomerService", "DepotAgent", "PlatformAdmin"}


def auth(allowed_roles):
    """Validate auth headers and role permission. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header", 401)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Role is not permitted for this operation", 403)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role is not permitted for this operation", 403)
    return user_id, role


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

STORE = {
    "customers": {},
    "devices": {},
    "coverage_plans": {},
    "service_locations": {},
    "technicians": {},
    "parts": {},
    "part_inventories": {},
    "appointments": {},
    "repair_orders": {},
    "part_allocations": {},
    "coverage_entitlements": {},
    "quality_follow_ups": {},
    "security_verifications": {},
    "repair_shipments": {},
}

# Serialized views for list endpoints, to keep created_at ordering stable.
# We keep dict insertion order = creation order, so lists iterate in created order.


def new_id():
    return str(uuid.uuid4())


def entity_bootstrap():
    """Return the common system fields for a fresh entity."""
    now = iso_z(logical_now())
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def touch(entity):
    """Bump version and refresh updated_at on a mutation."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = iso_z(logical_now())


# ---------------------------------------------------------------------------
# Request body / pagination helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON", 400)
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def require(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % f, 400)
    return data


def require_bool(data, *fields):
    for f in fields:
        if f not in data or not isinstance(data[f], bool):
            raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % f, 400)


def require_int(data, *fields):
    for f in fields:
        if f not in data or isinstance(data[f], bool) or not isinstance(data[f], int):
            raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid required field: %s" % f, 400)


def require_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for field: %s" % field, 400)
    return v


def pagination():
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return ok_list(window, limit, offset, total)


def opt_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return str(raw).lower() == "true"


# ---------------------------------------------------------------------------
# Entity lookup helpers
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "customers": ("ERR_CUSTOMER_NOT_FOUND", "Customer not found"),
    "devices": ("ERR_DEVICE_NOT_FOUND", "Device not found"),
    "appointments": ("ERR_APPOINTMENT_NOT_FOUND", "Appointment not found"),
    "repair_orders": ("ERR_REPAIR_ORDER_NOT_FOUND", "Repair order not found"),
    "coverage_plans": ("ERR_COVERAGE_PLAN_NOT_FOUND", "Coverage plan not found"),
    "service_locations": ("ERR_LOCATION_NOT_FOUND", "Service location not found"),
    "parts": ("ERR_PART_NOT_FOUND", "Part not found"),
}


def get_entity(coll, eid):
    e = STORE[coll].get(eid)
    if e is None:
        error_id, msg = _NOT_FOUND.get(coll, ("ERR_NOT_FOUND", "Resource not found"))
        raise ApiError(error_id, msg, 404)
    return e


def get_customer(eid):
    return get_entity("customers", eid)


def get_device(eid):
    return get_entity("devices", eid)


def get_appointment(eid):
    return get_entity("appointments", eid)


def get_repair_order(eid):
    return get_entity("repair_orders", eid)


def get_plan(eid):
    return get_entity("coverage_plans", eid)


def get_location(eid):
    return get_entity("service_locations", eid)


def get_part(eid):
    return get_entity("parts", eid)


# ---------------------------------------------------------------------------
# Lazy time-driven transitions
# ---------------------------------------------------------------------------

def _apply_lazy_transitions():
    now = logical_now()
    for a in STORE["appointments"].values():
        if a["appointment_status"] == "SCHEDULED":
            end = parse_iso(a["slot_end"])
            if now > end:
                a["appointment_status"] = "NO_SHOW"
                touch(a)
    for p in STORE["coverage_plans"].values():
        if p["coverage_status"] == "ACTIVE":
            exp = parse_iso(p["expires_on"])
            if now > exp:
                p["coverage_status"] = "EXPIRED"
                touch(p)
    for v in STORE["security_verifications"].values():
        if v["verification_status"] == "PENDING":
            created = parse_iso(v["created_at"])
            if now > created + timedelta(hours=24):
                v["verification_status"] = "EXPIRED"
                touch(v)


def install_lazy_hook(app):
    @app.before_request
    def _lazy():
        if request.path.startswith("/repair/"):
            _apply_lazy_transitions()


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _copy(e, fields):
    return {f: e.get(f) for f in fields}


_COMMON = ["id", "created_at", "updated_at", "version"]


def ser_customer(e):
    return _copy(e, _COMMON + ["email", "full_name", "phone", "account_status"])


def ser_device(e):
    return _copy(e, _COMMON + ["customer_id", "serial_number", "model_code",
                               "activation_lock_enabled", "proof_of_purchase_on_file",
                               "purchase_date", "device_status"])


def ser_plan(e):
    return _copy(e, _COMMON + ["device_id", "plan_type", "starts_on", "expires_on",
                               "accidental_damage_incidents_used",
                               "accidental_damage_incident_limit",
                               "service_fee_cents", "coverage_status"])


def ser_location(e):
    return _copy(e, _COMMON + ["location_code", "location_type", "address",
                               "supports_same_day_repair", "supports_express_replacement",
                               "diagnostic_slot_duration_minutes", "location_status"])


def ser_technician(e):
    return _copy(e, _COMMON + ["location_id", "full_name", "certification_level", "is_active"])


def ser_part(e):
    return _copy(e, _COMMON + ["part_number", "model_code", "part_category",
                               "is_whole_unit_replacement", "part_status"])


def ser_inventory(e):
    out = _copy(e, _COMMON + ["location_id", "part_id", "on_hand_quantity",
                              "reserved_quantity", "express_replacement_quantity"])
    out["available_quantity"] = (e["on_hand_quantity"] - e["reserved_quantity"]
                                 - e["express_replacement_quantity"])
    return out


def ser_appointment(e):
    return _copy(e, _COMMON + ["customer_id", "device_id", "location_id", "technician_id",
                               "slot_start", "slot_end", "issue_category", "appointment_status"])


def ser_repair_order(e):
    return _copy(e, _COMMON + ["appointment_id", "device_id", "customer_id",
                               "origin_location_id", "current_location_id", "issue_category",
                               "is_accidental_damage", "triage_mode", "repair_status",
                               "quoted_price_cents", "data_backup_acknowledged",
                               "privacy_wipe_consent", "repeat_repair_count"])


def ser_allocation(e):
    return _copy(e, _COMMON + ["repair_order_id", "part_id", "location_id", "quantity",
                               "allocation_status"])


def ser_entitlement(e):
    return _copy(e, _COMMON + ["repair_order_id", "coverage_plan_id", "entitlement_status",
                               "quoted_price_cents", "requires_proof_of_purchase",
                               "incident_counted"])


def ser_follow_up(e):
    return _copy(e, _COMMON + ["repair_order_id", "customer_id", "follow_up_status",
                               "opened_at", "resolved_at"])


def ser_verification(e):
    return _copy(e, _COMMON + ["repair_order_id", "verification_type", "verification_status",
                               "verified_by", "verified_at"])


def ser_shipment(e):
    return _copy(e, _COMMON + ["repair_order_id", "from_location_id", "to_location_id",
                               "shipment_type", "shipment_status", "tracking_number",
                               "shipped_at", "received_at"])


# ---------------------------------------------------------------------------
# Pricing & triage calculations
# ---------------------------------------------------------------------------

BASE_PRICE_BY_ISSUE = {
    "SCREEN_DAMAGE": 19900,
    "BATTERY": 6900,
    "WATER_DAMAGE": 39900,
    "SOFTWARE": 4900,
    "HARDWARE_OTHER": 29900,
}
AGE_SURCHARGE_RATE = 0.15
PREMIUM_MODELS = {"IPHONE_15_PRO", "IPHONE_15_PRO_MAX", "MACBOOK_PRO_16"}
PREMIUM_MODEL_MULTIPLIER = 1.25
PART_WEIGHT = {"DISPLAY": 3, "BATTERY": 2, "LOGIC_BOARD": 5, "CAMERA": 2, "ENCLOSURE": 1, "OTHER": 1}
SAME_DAY_THRESHOLD = 0.8
BUFFER_MINUTES = 10
BASE_SHIPPING_CENTS = 1500
ZONE_MULTIPLIER = {"ZONE_1": 1.0, "ZONE_2": 1.5, "ZONE_3": 2.0}
REPEAT_WINDOW_DAYS = 90

ISSUE_CATEGORIES = set(BASE_PRICE_BY_ISSUE.keys())

ISSUE_PART_CATEGORIES = {
    "SCREEN_DAMAGE": ["DISPLAY"],
    "BATTERY": ["BATTERY"],
    "WATER_DAMAGE": ["LOGIC_BOARD", "BATTERY"],
    "SOFTWARE": ["OTHER"],
    "HARDWARE_OTHER": ["LOGIC_BOARD"],
}


def round_half_up_int(x):
    """Round a float to whole cents using round-half-up, returned as int."""
    import math
    return int(math.floor(x + 0.5))


def out_of_warranty_price(device, issue_category):
    base = BASE_PRICE_BY_ISSUE[issue_category]
    purchase = parse_iso(device["purchase_date"])
    age_years = (logical_now() - purchase).total_seconds() / (365.25 * 86400)
    age_surcharge = base * AGE_SURCHARGE_RATE if age_years > 2 else 0
    multiplier = PREMIUM_MODEL_MULTIPLIER if device.get("model_code") in PREMIUM_MODELS else 1.0
    price = (base + age_surcharge) * multiplier
    return max(0, round_half_up_int(price))


def required_parts_for(order):
    """Component parts matching the order's issue categories and device model."""
    device = STORE["devices"].get(order["device_id"]) or {}
    model_code = device.get("model_code")
    cats = ISSUE_PART_CATEGORIES.get(order["issue_category"], ["OTHER"])
    parts = [p for p in STORE["parts"].values()
             if p.get("model_code") == model_code
             and p.get("part_category") in cats
             and not p.get("is_whole_unit_replacement")
             and p.get("part_status") == "ACTIVE"]
    return parts


def inventory_at(location_id, part_id):
    for inv in STORE["part_inventories"].values():
        if inv["location_id"] == location_id and inv["part_id"] == part_id:
            return inv
    return None


def compute_triage_mode(order):
    device = STORE["devices"].get(order["device_id"]) or {}
    model_code = device.get("model_code")
    loc = order["current_location_id"]
    # Whole-unit replacement bypass: an ACTIVE whole-unit part for the model
    # with express_replacement_quantity > 0 at the location.
    for p in STORE["parts"].values():
        if (p.get("model_code") == model_code and p.get("is_whole_unit_replacement")
                and p.get("part_status") == "ACTIVE"):
            inv = inventory_at(loc, p["id"])
            if inv is not None and inv.get("express_replacement_quantity", 0) > 0:
                return "WHOLE_UNIT_REPLACEMENT"
    parts = required_parts_for(order)
    if not parts:
        return "MAIL_IN_DEPOT"
    total_weight = 0.0
    weighted = 0.0
    for p in parts:
        w = PART_WEIGHT.get(p["part_category"], 1)
        inv = inventory_at(loc, p["id"])
        available = 0
        if inv is not None:
            available = inv["on_hand_quantity"] - inv["reserved_quantity"] - inv["express_replacement_quantity"]
        score = min(max(available, 0) / 1.0, 1.0)
        weighted += score * w
        total_weight += w
    total_score = round(weighted / total_weight, 2) if total_weight > 0 else 0.0
    if total_score >= SAME_DAY_THRESHOLD:
        return "SAME_DAY_IN_STORE"
    return "MAIL_IN_DEPOT"


def nearest_depot_zone(from_location_id, to_location_id):
    """Heuristic distance zone between two locations (distinct ids)."""
    if from_location_id == to_location_id:
        return None
    a, b = sorted([str(from_location_id), str(to_location_id)])
    h = 0
    for ch in (a + "|" + b):
        h = (h * 131 + ord(ch)) % 9973
    return ("ZONE_1", "ZONE_2", "ZONE_3")[h % 3]


def depot_shipping_cost(from_location_id, to_location_id):
    if from_location_id == to_location_id:
        return 0
    zone = nearest_depot_zone(from_location_id, to_location_id)
    cost = BASE_SHIPPING_CENTS * ZONE_MULTIPLIER[zone]
    return max(0, round_half_up_int(cost))
