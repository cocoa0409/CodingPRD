"""Reference data: customers, catalog models, production lines, field
engineers, and the logical-clock test hook (PRD 3.1, 2.5)."""
from decimal import Decimal

from flask import Blueprint

import auth
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("foundation", __name__)

REGIONS = ("NA", "EU", "APAC", "LATAM")
FAMILIES = ("FILLER", "CAPPER", "LABELER", "CARTONER")
READ_ALL = ("PlatformAdmin", "ApplicationEngineer", "ProductionPlanner",
            "QualityInspector", "ServiceManager", "CustomerContact")


# --------------------------------------------------------------------------
# customers
# --------------------------------------------------------------------------
@bp.post("/customers")
def create_customer():
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    row = {
        "legal_name": validation.req_str(payload, "legal_name", 1, 120),
        "region_code": validation.req_enum(payload, "region_code", REGIONS),
        "product_variation_pct": validation.req_pct(
            payload, "product_variation_pct", Decimal("0.00"), Decimal("40.00")),
        "status": "ACTIVE",
        "open_order_count": 0,
    }
    return envelope.created(store.insert("customers", row))


@bp.get("/customers/<customer_id>")
def read_customer(customer_id):
    auth.authorize(READ_ALL)
    return envelope.ok(domain.must_get("customers", customer_id))


@bp.post("/customers/<customer_id>/suspend")
def suspend_customer(customer_id):
    auth.authorize(("PlatformAdmin",))
    customer = domain.must_get("customers", customer_id)
    customer["status"] = "SUSPENDED"
    store.touch(customer)
    return envelope.ok(customer)


# --------------------------------------------------------------------------
# machine models
# --------------------------------------------------------------------------
@bp.post("/machine-models")
def create_machine_model():
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    model_code = validation.req_str(payload, "model_code", 3, 32)
    machine_family = validation.req_enum(payload, "machine_family", FAMILIES)
    nameplate_rate_cpm = validation.req_int(payload, "nameplate_rate_cpm", 1)
    guarantee_efficiency_pct = validation.req_pct(
        payload, "guarantee_efficiency_pct", Decimal("50.00"), Decimal("100.00"))
    base_price_cents = validation.req_int(payload, "base_price_cents", 0)
    min_diameter = validation.req_int(payload, "min_container_diameter_mm", 1)
    max_diameter = validation.req_int(payload, "max_container_diameter_mm", 1)
    if max_diameter < min_diameter:
        raise validation.invalid(
            "Field 'max_container_diameter_mm' must be at least "
            "'min_container_diameter_mm'.")
    for existing in store.rows("machine_models"):
        if existing["model_code"] == model_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "model_code '%s' is already published." % model_code)
    row = {
        "model_code": model_code,
        "machine_family": machine_family,
        "nameplate_rate_cpm": nameplate_rate_cpm,
        "guarantee_efficiency_pct": guarantee_efficiency_pct,
        "base_price_cents": base_price_cents,
        "min_container_diameter_mm": min_diameter,
        "max_container_diameter_mm": max_diameter,
        "lifecycle_status": "ACTIVE",
        "open_defect_review_count": 0,
    }
    return envelope.created(store.insert("machine_models", row))


@bp.get("/machine-models/<machine_model_id>")
def read_machine_model(machine_model_id):
    auth.authorize(READ_ALL)
    return envelope.ok(domain.must_get("machine_models", machine_model_id))


@bp.post("/machine-models/<machine_model_id>/obsolete")
def obsolete_machine_model(machine_model_id):
    auth.authorize(("PlatformAdmin",))
    model = domain.must_get("machine_models", machine_model_id)
    model["lifecycle_status"] = "OBSOLETE"
    store.touch(model)
    return envelope.ok(model)


# --------------------------------------------------------------------------
# production lines
# --------------------------------------------------------------------------
@bp.post("/production-lines")
def create_production_line():
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    line_code = validation.req_str(payload, "line_code", 2, 24)
    machine_family = validation.req_enum(payload, "machine_family", FAMILIES)
    changeover_buffer_days = validation.req_int(payload, "changeover_buffer_days", 0)
    capacity_days_per_quarter = validation.req_int(
        payload, "capacity_days_per_quarter", 1)
    for existing in store.rows("production_lines"):
        if existing["line_code"] == line_code:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "line_code '%s' already exists." % line_code)
    row = {
        "line_code": line_code,
        "machine_family": machine_family,
        "changeover_buffer_days": changeover_buffer_days,
        "capacity_days_per_quarter": capacity_days_per_quarter,
        "committed_slot_days": 0,
        "status": "OPEN",
    }
    return envelope.created(store.insert("production_lines", row))


@bp.get("/production-lines/<production_line_id>")
def read_production_line(production_line_id):
    auth.authorize(("PlatformAdmin", "ProductionPlanner", "ApplicationEngineer",
                    "QualityInspector"))
    return envelope.ok(domain.must_get("production_lines", production_line_id))


@bp.post("/production-lines/<production_line_id>/maintenance-hold")
def hold_production_line(production_line_id):
    auth.authorize(("PlatformAdmin",))
    line = domain.must_get("production_lines", production_line_id)
    line["status"] = "MAINTENANCE"
    store.touch(line)
    return envelope.ok(line)


# --------------------------------------------------------------------------
# field engineers
# --------------------------------------------------------------------------
@bp.post("/field-engineers")
def create_field_engineer():
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    full_name = validation.req_str(payload, "full_name", 1, 80)
    region_code = validation.req_enum(payload, "region_code", REGIONS)
    raw_certs = validation.opt_list(payload, "certifications", [])
    certifications = []
    for item in raw_certs:
        if not isinstance(item, str) or not item.strip():
            raise validation.invalid(
                "Field 'certifications' must be an array of strings.")
        certifications.append(item)
    travel_buffer_minutes = validation.opt_int(
        payload, "travel_buffer_minutes", 0, None, 0)
    row = {
        "full_name": full_name,
        "region_code": region_code,
        "certifications": certifications,
        "travel_buffer_minutes": travel_buffer_minutes,
        "status": "AVAILABLE",
    }
    return envelope.created(store.insert("field_engineers", row))


@bp.get("/field-engineers/<field_engineer_id>")
def read_field_engineer(field_engineer_id):
    auth.authorize(("PlatformAdmin", "ServiceManager"))
    return envelope.ok(domain.must_get("field_engineers", field_engineer_id))


@bp.post("/field-engineers/<field_engineer_id>/leave")
def engineer_leave(field_engineer_id):
    auth.authorize(("PlatformAdmin",))
    engineer = domain.must_get("field_engineers", field_engineer_id)
    engineer["status"] = "ON_LEAVE"
    store.touch(engineer)
    return envelope.ok(engineer)


# --------------------------------------------------------------------------
# logical clock (mutates no entity row -- PRD 2.5)
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    instant = validation.req_instant(payload, "to_iso8601")
    store.set_now(instant)
    return envelope.ok({"current_utc": store.now_iso()})
