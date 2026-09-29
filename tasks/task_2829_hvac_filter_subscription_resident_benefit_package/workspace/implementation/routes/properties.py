"""Properties and their units (PRD 3.2)."""
from flask import Blueprint

import calc
import envelope
import guards
import services
import validate
import views
from errors import fail
from store import base_record, db, touch

bp = Blueprint("properties", __name__)

BILLING_MODES = ("PM_BILLED", "RESIDENT_PAID")
BENEFIT_TIERS = ("BASIC", "PLUS", "PREMIUM")
PROPERTY_STATUSES = ("ONBOARDING", "ACTIVE", "SUSPENDED", "OFFBOARDED")
UNIT_STATUSES = ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE")
HVAC_TYPES = ("SINGLE_STAGE", "TWO_STAGE", "VARIABLE_SPEED", "HEAT_PUMP")


@bp.post("/properties")
def create_property():
    guards.auth(["ProgramOperator"])
    body = validate.json_body()
    name = validate.req_string(body, "name", 1, 120)
    state_code = validate.req_string(body, "state_code",
                                     pattern=validate.STATE_CODE_RE)
    billing_mode = validate.req_enum(body, "billing_mode", BILLING_MODES)
    benefit_tier = validate.req_enum(body, "benefit_tier", BENEFIT_TIERS)
    damage_waiver = validate.req_bool(body, "damage_waiver_enabled")
    aqg = validate.req_bool(body, "aqg_enabled")
    credit_limit = validate.req_int(body, "credit_limit_cents", 0)

    rec = base_record()
    rec["name"] = name
    rec["state_code"] = state_code
    rec["billing_mode"] = billing_mode
    rec["benefit_tier"] = benefit_tier
    rec["damage_waiver_enabled"] = damage_waiver
    rec["aqg_enabled"] = aqg
    rec["credit_limit_cents"] = credit_limit
    rec["status"] = "ONBOARDING"
    rec["suspend_reason"] = None
    rec["outstanding_balance_cents"] = 0
    rec["unit_count"] = 0
    db.properties[rec["id"]] = rec
    return envelope.object_response(views.property_view(rec), 201)


@bp.get("/properties/<property_id>")
def read_property(property_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    rec = guards.get_property(property_id)
    guards.own_property(uid, role, rec["id"])
    return envelope.object_response(views.property_view(rec))


@bp.get("/properties")
def list_properties():
    guards.auth(["ProgramOperator"])
    limit, offset, filters = guards.pagination({
        "status": PROPERTY_STATUSES,
        "billing_mode": BILLING_MODES,
        "benefit_tier": BENEFIT_TIERS,
    })
    rows = [p for p in db.properties.values()
            if all(p[k] == v for k, v in filters.items())]
    rows = calc.sorted_rows(rows)
    return envelope.list_response([views.property_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/properties/<property_id>/activate")
def activate_property(property_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_property(property_id)
    if rec["status"] != "ONBOARDING":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the property is not ONBOARDING")
    if calc.unit_count(rec["id"]) < 1:
        fail("ERR_PROPERTY_NOT_ACTIVE",
             "the property must hold at least one unit before activation")
    rec["status"] = "ACTIVE"
    rec["suspend_reason"] = None
    touch(rec)
    return envelope.object_response(views.property_view(rec))


@bp.post("/properties/<property_id>/suspend")
def suspend_property(property_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_property(property_id)
    body = validate.json_body()
    reason = validate.req_text(body, "suspend_reason")
    if rec["status"] != "ACTIVE":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the property is not ACTIVE")
    rec["status"] = "SUSPENDED"
    rec["suspend_reason"] = reason
    touch(rec)
    services.suspend_property_cascade(rec)
    return envelope.object_response(views.property_view(rec))


@bp.post("/properties/<property_id>/reactivate")
def reactivate_property(property_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_property(property_id)
    if rec["status"] != "SUSPENDED":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the property is not SUSPENDED")
    rec["status"] = "ACTIVE"
    rec["suspend_reason"] = None
    touch(rec)
    services.reactivate_property_cascade(rec)
    return envelope.object_response(views.property_view(rec))


@bp.post("/properties/<property_id>/offboard")
def offboard_property(property_id):
    guards.auth(["ProgramOperator"])
    rec = guards.get_property(property_id)
    if rec["status"] != "SUSPENDED":
        fail("ERR_PROPERTY_NOT_ACTIVE", "the property is not SUSPENDED")
    blocking = [s for s in calc.subscriptions_of_property(rec["id"])
                if s["status"] in ("PENDING_SETUP", "ACTIVE", "TRANSFER_PENDING")]
    if blocking:
        fail("ERR_PROPERTY_NOT_ACTIVE",
             "the property still has live subscriptions")
    rec["status"] = "OFFBOARDED"
    touch(rec)
    for unit in calc.units_of(rec["id"]):
        if unit["status"] in ("AVAILABLE", "OCCUPIED"):
            unit["status"] = "OUT_OF_SERVICE"
            touch(unit)
    return envelope.object_response(views.property_view(rec))


@bp.get("/properties/<property_id>/units")
def list_units(property_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    prop = guards.get_property(property_id)
    guards.own_property(uid, role, prop["id"])
    limit, offset, filters = guards.pagination({"status": UNIT_STATUSES})
    rows = [u for u in calc.units_of(prop["id"])
            if all(u[k] == v for k, v in filters.items())]
    return envelope.list_response([views.unit_view(r) for r in
                                  guards.page(rows, limit, offset)],
                                 limit, offset, len(rows))


@bp.post("/properties/<property_id>/units")
def create_unit(property_id):
    uid, role = guards.auth(["ProgramOperator", "PropertyManager"])
    prop = guards.get_property(property_id)
    guards.own_property(uid, role, prop["id"])
    body = validate.json_body()
    label = validate.req_string(body, "unit_label", 1, 24)
    hvac = validate.req_enum(body, "hvac_system_type", HVAC_TYPES)
    slots = validate.req_int(body, "filter_slot_count", 1, 6)
    grilles = validate.req_int(body, "return_grille_count", 1, 6)
    nominal = validate.req_string(body, "nominal_size_code",
                                  pattern=validate.SIZE_CODE_RE)
    for existing in calc.units_of(prop["id"]):
        if existing["unit_label"] == label:
            fail("ERR_INVALID_REQUEST", "unit_label must be unique per property")

    rec = base_record()
    rec["property_id"] = prop["id"]
    rec["unit_label"] = label
    rec["hvac_system_type"] = hvac
    rec["filter_slot_count"] = slots
    rec["return_grille_count"] = grilles
    rec["nominal_size_code"] = nominal
    rec["actual_measured_size_code"] = None
    rec["size_capture_count"] = 0
    rec["status"] = "AVAILABLE"
    db.units[rec["id"]] = rec
    return envelope.object_response(views.unit_view(rec), 201)
