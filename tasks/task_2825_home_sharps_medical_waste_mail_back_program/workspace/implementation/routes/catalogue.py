"""State rules, packaging specifications and treatment facilities (PRD 3.1)."""
import re

from flask import Blueprint

import constants
import db
import response
import validate
from errors import (
    ERR_DUPLICATE_PERMIT_NUMBER,
    ERR_DUPLICATE_SPEC_CODE,
    ERR_DUPLICATE_STATE_RULE,
    ERR_INVALID_FACILITY_STATE,
    ERR_INVALID_REQUEST,
    fail,
)
from middleware import endpoint
from routes.common import page
from services import lookup
from validate import Field

bp = Blueprint("catalogue", __name__)

READ_STATE_RULE_ROLES = (
    "ProgramAdmin",
    "LogisticsCoordinator",
    "IntakeTechnician",
    "DestructionOfficer",
    "SponsorRepresentative",
)
READ_SPEC_ROLES = ("ProgramAdmin", "LogisticsCoordinator", "IntakeTechnician")
READ_FACILITY_ROLES = (
    "ProgramAdmin",
    "LogisticsCoordinator",
    "IntakeTechnician",
    "DestructionOfficer",
)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

STATE_RULE_SCHEMA = [
    Field("state_code", "string", required=True, min_len=2, max_len=2),
    Field(
        "household_sharps_classification",
        "enum",
        required=True,
        values=constants.HOUSEHOLD_SHARPS_CLASSIFICATIONS,
    ),
    Field("mail_back_permitted", "bool", required=True),
    Field("max_container_volume_liters", "number", required=True, gt=0),
    Field("certificate_retention_years", "int", required=True, minimum=0, maximum=30),
    Field("requires_state_manifest", "bool", default=False),
    Field("notification_deadline_hours", "int", default=72, minimum=1, maximum=720),
]

SPEC_SCHEMA = [
    Field("spec_code", "string", required=True, min_len=1, max_len=32),
    Field("un_specification_code", "string", required=True, min_len=1),
    Field("postal_service", "enum", required=True, values=constants.POSTAL_SERVICES),
    Field("hazard_class", "enum", required=True, values=constants.HAZARD_CLASSES),
    Field("max_gross_weight_grams", "int", required=True, minimum=100, maximum=31700),
    Field(
        "allowed_container_sizes",
        "array_enum",
        required=True,
        item_values=constants.CONTAINER_SIZES,
        non_empty=True,
    ),
    Field("requires_absorbent", "bool", default=False),
    Field("status", "enum", default="ACTIVE", values=constants.SPEC_STATUSES),
]

FACILITY_SCHEMA = [
    Field("name", "string", required=True, min_len=1),
    Field("state_rule_id", "string", required=True, min_len=1),
    Field("permit_number", "string", required=True, min_len=1, max_len=32),
    Field(
        "accepted_hazard_classes",
        "array_enum",
        required=True,
        item_values=constants.HAZARD_CLASSES,
        non_empty=True,
    ),
    Field("daily_intake_capacity_units", "int", required=True, minimum=1, maximum=100000),
    Field("status", "enum", default="ACTIVE", values=constants.FACILITY_STATUSES),
]

STATUS_ACTION_SCHEMA = [
    Field("action", "enum", required=True, values=["SUSPEND", "REINSTATE"]),
    Field("reason", "string"),
]


# ---- state rules --------------------------------------------------------

@bp.post("/sharps/state-rules")
@endpoint(["ProgramAdmin"])
def create_state_rule():
    body, _provided = validate.parse_body(STATE_RULE_SCHEMA)
    if not STATE_CODE_RE.match(body["state_code"]):
        fail(ERR_INVALID_REQUEST, "Field 'state_code' must be exactly two uppercase letters.")
    for existing in db.coll("state_rules").values():
        if existing["state_code"] == body["state_code"]:
            fail(ERR_DUPLICATE_STATE_RULE)
    row = db.create_row("state_rules", body)
    return response.created(response.view("state_rule", row))


@bp.get("/sharps/state-rules/<rule_id>")
@endpoint(READ_STATE_RULE_ROLES, mutating=False)
def get_state_rule(rule_id):
    row = lookup.require("state_rule", rule_id)
    return response.ok(response.view("state_rule", row))


@bp.get("/sharps/state-rules")
@endpoint(READ_STATE_RULE_ROLES, mutating=False)
def list_state_rules():
    limit, offset = validate.pagination()
    state_code = validate.qs_str("state_code")
    mail_back = validate.qs_bool("mail_back_permitted")
    rows = db.ordered("state_rules")
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if mail_back is not None:
        rows = [r for r in rows if r["mail_back_permitted"] == mail_back]
    return page("state_rule", rows, limit, offset)


# ---- packaging specs ----------------------------------------------------

@bp.post("/sharps/packaging-specs")
@endpoint(["ProgramAdmin"])
def create_packaging_spec():
    body, _provided = validate.parse_body(SPEC_SCHEMA)
    for existing in db.coll("packaging_specs").values():
        if existing["spec_code"] == body["spec_code"]:
            fail(ERR_DUPLICATE_SPEC_CODE)
    row = db.create_row("packaging_specs", body)
    return response.created(response.view("packaging_spec", row))


@bp.get("/sharps/packaging-specs/<spec_id>")
@endpoint(READ_SPEC_ROLES, mutating=False)
def get_packaging_spec(spec_id):
    row = lookup.require("packaging_spec", spec_id)
    return response.ok(response.view("packaging_spec", row))


@bp.get("/sharps/packaging-specs")
@endpoint(READ_SPEC_ROLES, mutating=False)
def list_packaging_specs():
    limit, offset = validate.pagination()
    postal_service = validate.qs_enum("postal_service", constants.POSTAL_SERVICES)
    hazard_class = validate.qs_enum("hazard_class", constants.HAZARD_CLASSES)
    status = validate.qs_enum("status", constants.SPEC_STATUSES)
    rows = db.ordered("packaging_specs")
    if postal_service is not None:
        rows = [r for r in rows if r["postal_service"] == postal_service]
    if hazard_class is not None:
        rows = [r for r in rows if r["hazard_class"] == hazard_class]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("packaging_spec", rows, limit, offset)


# ---- treatment facilities ----------------------------------------------

@bp.post("/sharps/treatment-facilities")
@endpoint(["ProgramAdmin"])
def create_facility():
    body, _provided = validate.parse_body(FACILITY_SCHEMA)
    lookup.require("state_rule", body["state_rule_id"])
    for existing in db.coll("treatment_facilities").values():
        if existing["permit_number"] == body["permit_number"]:
            fail(ERR_DUPLICATE_PERMIT_NUMBER)
    body["pending_intake_units"] = 0
    body["destroyed_units_total"] = 0
    body["certificates_issued_count"] = 0
    row = db.create_row("treatment_facilities", body)
    return response.created(response.view("treatment_facility", row))


@bp.post("/sharps/treatment-facilities/<facility_id>/status-actions")
@endpoint(["ProgramAdmin"])
def facility_status_action(facility_id):
    body, _provided = validate.parse_body(STATUS_ACTION_SCHEMA)
    facility = lookup.require("facility", facility_id)
    if body["action"] == "SUSPEND":
        if facility["status"] != "ACTIVE":
            fail(ERR_INVALID_FACILITY_STATE)
        facility["status"] = "SUSPENDED"
    else:
        if facility["status"] != "SUSPENDED":
            fail(ERR_INVALID_FACILITY_STATE)
        facility["status"] = "ACTIVE"
    db.bump(facility)
    return response.ok(response.view("treatment_facility", facility))


@bp.get("/sharps/treatment-facilities/<facility_id>")
@endpoint(READ_FACILITY_ROLES, mutating=False)
def get_facility(facility_id):
    row = lookup.require("facility", facility_id)
    return response.ok(response.view("treatment_facility", row))


@bp.get("/sharps/treatment-facilities")
@endpoint(READ_FACILITY_ROLES, mutating=False)
def list_facilities():
    limit, offset = validate.pagination()
    status = validate.qs_enum("status", constants.FACILITY_STATUSES)
    state_rule_id = validate.qs_str("state_rule_id")
    lookup.require_filter("state_rule", state_rule_id)
    rows = db.ordered("treatment_facilities")
    if state_rule_id is not None:
        rows = [r for r in rows if r["state_rule_id"] == state_rule_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return page("treatment_facility", rows, limit, offset)
