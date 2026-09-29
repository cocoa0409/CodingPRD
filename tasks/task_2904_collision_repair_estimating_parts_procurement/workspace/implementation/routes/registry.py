"""Standing registries and the logical-clock test hook (PRD 3.1, 2.4)."""
from flask import Blueprint

import auth
import calc
import db
import response
import serialize
import validate
from db import store
from errors import raise_error
from validate import F

bp = Blueprint("registry", __name__)

PART_TYPES = ("OEM", "AFTERMARKET", "RECYCLED", "RECONDITIONED")
VENDOR_TYPES = ("OEM_DEALER", "AFTERMARKET_DISTRIBUTOR", "RECYCLER", "RECONDITIONER")
VENDOR_STATUSES = ("ACTIVE", "SUSPENDED")
STALL_TYPES = ("BODY", "FRAME", "PAINT")
STALL_STATUSES = ("AVAILABLE", "MAINTENANCE")
CALIBRATION_TYPES = ("STATIC", "DYNAMIC", "BOTH")


def _members(values, allowed, field_name):
    for value in values:
        if not isinstance(value, str) or value not in allowed:
            raise_error("ERR_INVALID_ENUM_VALUE",
                        "Field '%s' members must be one of %s."
                        % (field_name, ", ".join(allowed)))


# --- vehicle owners --------------------------------------------------------------------
CUSTOMER_SPEC = [
    F("full_name", "string", required=True),
    F("phone", "string", required=True),
    F("email", "string", required=True),
    F("preferred_alternate_parts_ok", "boolean", default=False),
]


@bp.route("/customers", methods=["POST"])
def create_customer():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(CUSTOMER_SPEC)
    row = db.base_row(mutable=False)
    row.update({
        "full_name": data["full_name"],
        "phone": data["phone"],
        "email": data["email"],
        "preferred_alternate_parts_ok": bool(data["preferred_alternate_parts_ok"]),
    })
    store.customers[row["id"]] = row
    return response.created(serialize.customer(row))


@bp.route("/customers/<row_id>", methods=["GET"])
def read_customer(row_id):
    auth.authenticate(("ShopAdmin", "Estimator"))
    row = store.customers.get(row_id)
    if row is None:
        raise_error("ERR_CUSTOMER_NOT_FOUND")
    return response.ok(serialize.customer(row))


# --- insurer programs ------------------------------------------------------------------
INSURER_SPEC = [
    F("insurer_code", "string", required=True),
    F("name", "string", required=True),
    F("rate_ceiling_cents", "object", required=True),
    F("aftermarket_allowed", "boolean", default=True),
    F("recycled_allowed", "boolean", default=True),
    F("reconditioned_allowed", "boolean", default=False),
    F("alternate_parts_min_vehicle_age_years", "integer", default=3),
    F("parts_price_ceiling_pct", "number", default=1.1),
    F("supplement_round_limit", "integer", default=3),
]


@bp.route("/insurers", methods=["POST"])
def create_insurer():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(INSURER_SPEC)
    code = data["insurer_code"]
    validate.require(3 <= len(code) <= 16, "insurer_code must be 3 to 16 characters.")
    validate.require(
        all(existing["insurer_code"] != code for existing in store.insurers.values()),
        "insurer_code must be unique.")
    ceilings = data["rate_ceiling_cents"]
    for labor_type in calc.LABOR_TYPES:
        validate.require(labor_type in ceilings,
                         "rate_ceiling_cents requires the key %s." % labor_type)
        value = ceilings[labor_type]
        validate.require(isinstance(value, int) and not isinstance(value, bool),
                         "rate_ceiling_cents.%s must be an integer." % labor_type)
    validate.require(data["alternate_parts_min_vehicle_age_years"] >= 0,
                     "alternate_parts_min_vehicle_age_years must be >= 0.")
    validate.require(float(data["parts_price_ceiling_pct"]) >= 1.0,
                     "parts_price_ceiling_pct must be at least 1.0.")
    validate.require(data["supplement_round_limit"] >= 1,
                     "supplement_round_limit must be at least 1.")

    row = db.base_row()
    row.update({
        "insurer_code": code,
        "name": data["name"],
        "aftermarket_allowed": bool(data["aftermarket_allowed"]),
        "recycled_allowed": bool(data["recycled_allowed"]),
        "reconditioned_allowed": bool(data["reconditioned_allowed"]),
        "alternate_parts_min_vehicle_age_years": data["alternate_parts_min_vehicle_age_years"],
        "rate_ceiling_cents": dict(ceilings),
        "parts_price_ceiling_pct": data["parts_price_ceiling_pct"],
        "supplement_round_limit": data["supplement_round_limit"],
    })
    store.insurers[row["id"]] = row
    return response.created(serialize.insurer(row))


@bp.route("/insurers/<row_id>", methods=["GET"])
def read_insurer(row_id):
    auth.authenticate(("ShopAdmin", "Estimator"))
    row = store.insurers.get(row_id)
    if row is None:
        raise_error("ERR_INSURER_NOT_FOUND")
    return response.ok(serialize.insurer(row))


# --- parts suppliers -------------------------------------------------------------------
VENDOR_SPEC = [
    F("name", "string", required=True),
    F("vendor_type", "string", required=True, enum=VENDOR_TYPES),
    F("part_types_offered", "array", required=True),
    F("status", "string", enum=VENDOR_STATUSES, default="ACTIVE"),
    F("discount_pct", "number", default=0),
    F("core_charge_cents", "integer", default=0),
    F("restocking_fee_pct", "number", default=0.2),
    F("max_qty_per_line", "integer", default=4),
]


@bp.route("/parts-vendors", methods=["POST"])
def create_parts_vendor():
    auth.authenticate(("ShopAdmin", "PartsManager"))
    data = validate.body(VENDOR_SPEC)
    offered = data["part_types_offered"]
    _members(offered, PART_TYPES, "part_types_offered")
    validate.require(len(offered) > 0, "part_types_offered must be non-empty.")
    validate.require(len(set(offered)) == len(offered),
                     "part_types_offered members must be unique.")
    validate.require(0 <= float(data["discount_pct"]) < 1,
                     "discount_pct must be >= 0 and < 1.")
    validate.require(data["core_charge_cents"] >= 0, "core_charge_cents must be >= 0.")
    validate.require(0 <= float(data["restocking_fee_pct"]) <= 1,
                     "restocking_fee_pct must be between 0 and 1 inclusive.")
    validate.require(data["max_qty_per_line"] >= 1, "max_qty_per_line must be >= 1.")

    row = db.base_row()
    row.update({
        "name": data["name"],
        "vendor_type": data["vendor_type"],
        "part_types_offered": list(offered),
        "status": data["status"],
        "discount_pct": data["discount_pct"],
        "core_charge_cents": data["core_charge_cents"],
        "restocking_fee_pct": data["restocking_fee_pct"],
        "max_qty_per_line": data["max_qty_per_line"],
        "order_seq_counter": 0,
        "fulfillment_score_rolling": calc.NEW_VENDOR_DEFAULT_SCORE,
        "fulfillment_score_lifetime": calc.NEW_VENDOR_DEFAULT_SCORE,
    })
    store.parts_vendors[row["id"]] = row
    return response.created(serialize.parts_vendor(row))


@bp.route("/parts-vendors/<row_id>", methods=["GET"])
def read_parts_vendor(row_id):
    auth.authenticate(("ShopAdmin", "PartsManager"))
    row = store.parts_vendors.get(row_id)
    if row is None:
        raise_error("ERR_PARTS_VENDOR_NOT_FOUND")
    return response.ok(serialize.parts_vendor(row))


# --- production capacity ---------------------------------------------------------------
STALL_SPEC = [
    F("name", "string", required=True),
    F("stall_type", "string", required=True, enum=STALL_TYPES),
    F("cleanup_buffer_minutes", "integer", default=30),
    F("status", "string", enum=STALL_STATUSES, default="AVAILABLE"),
]


@bp.route("/stalls", methods=["POST"])
def create_stall():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(STALL_SPEC)
    validate.require(data["cleanup_buffer_minutes"] >= 0,
                     "cleanup_buffer_minutes must be >= 0.")
    row = db.base_row()
    row.update({
        "name": data["name"],
        "stall_type": data["stall_type"],
        "cleanup_buffer_minutes": data["cleanup_buffer_minutes"],
        "status": data["status"],
        "booked_minutes": 0,
    })
    store.stalls[row["id"]] = row
    return response.created(serialize.stall(row))


@bp.route("/stalls/<row_id>", methods=["GET"])
def read_stall(row_id):
    auth.authenticate(("ShopAdmin", "Technician"))
    row = store.stalls.get(row_id)
    if row is None:
        raise_error("ERR_STALL_NOT_FOUND")
    return response.ok(serialize.stall(row))


BAY_SPEC = [
    F("name", "string", required=True),
    F("supported_types", "array", required=True),
    F("concurrent_capacity", "integer", default=2),
]


@bp.route("/calibration-bays", methods=["POST"])
def create_calibration_bay():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(BAY_SPEC)
    supported = data["supported_types"]
    _members(supported, CALIBRATION_TYPES, "supported_types")
    validate.require(len(supported) > 0, "supported_types must be non-empty.")
    validate.require(len(set(supported)) == len(supported),
                     "supported_types members must be unique.")
    validate.require(data["concurrent_capacity"] >= 1, "concurrent_capacity must be >= 1.")
    row = db.base_row()
    row.update({
        "name": data["name"],
        "supported_types": list(supported),
        "concurrent_capacity": data["concurrent_capacity"],
        "scheduled_window_count": 0,
    })
    store.calibration_bays[row["id"]] = row
    return response.created(serialize.calibration_bay(row))


@bp.route("/calibration-bays/<row_id>", methods=["GET"])
def read_calibration_bay(row_id):
    auth.authenticate(("ShopAdmin", "Technician"))
    row = store.calibration_bays.get(row_id)
    if row is None:
        raise_error("ERR_CALIBRATION_BAY_NOT_FOUND")
    return response.ok(serialize.calibration_bay(row))


# --- the logical clock -----------------------------------------------------------------
CLOCK_SPEC = [F("to_iso8601", "string", required=True)]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.authenticate(("ShopAdmin",))
    data = validate.body(CLOCK_SPEC)
    instant = validate.instant(data["to_iso8601"],
                               "to_iso8601 must be an ISO-8601 instant.")
    db.set_clock(instant)
    return response.ok({"current_utc": db.now_iso()})
