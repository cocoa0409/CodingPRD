"""Facility and Operator standing-data endpoints (PRD 3.1)."""

from flask import Blueprint

from constants import (
    FACILITY_BASE_RATE_MAX,
    FACILITY_BASE_RATE_MIN,
    FACILITY_STATUSES,
    FACILITY_TYPES,
    OPERATOR_TYPES,
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLES,
)
from errors import ApiError
from serialize import serialize_facility, serialize_operator
from storage import DB, create_entity, touch
from util import (
    body_json,
    opt_bool,
    opt_enum,
    opt_int,
    req_enum,
    req_int,
    req_str,
    success_object,
)
from validation import auth_context, get_facility, get_operator, require_roles

bp = Blueprint("facilities", __name__)


@bp.route("/atfm/facilities", methods=["POST"])
def create_facility():
    auth_context()
    require_roles(ROLE_SYSTEM_ADMINISTRATOR)
    body = body_json()
    ident = req_str(body, "ident")
    facility_type = req_enum(body, "facility_type", FACILITY_TYPES)
    base_rate = req_int(body, "base_acceptance_rate")
    if not (FACILITY_BASE_RATE_MIN <= base_rate <= FACILITY_BASE_RATE_MAX):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "base_acceptance_rate must be an integer in [1, 120]",
        )
    status = opt_enum(body, "status", FACILITY_STATUSES, "OPERATIONAL")
    # Priority 12: ident uniqueness across all facilities.
    if any(f["ident"] == ident for f in DB["facilities"].values()):
        raise ApiError(
            "ERR_FACILITY_IDENT_CONFLICT", "facility ident %s is already registered" % ident
        )
    rec = create_entity(
        "facilities",
        {
            "ident": ident,
            "facility_type": facility_type,
            "base_acceptance_rate": base_rate,
            "status": status,
        },
    )
    return success_object(serialize_facility(rec), 201)


@bp.route("/atfm/facilities/<facility_id>", methods=["GET"])
def fetch_facility(facility_id):
    auth_context()
    require_roles(*ROLES)
    rec = get_facility(facility_id)
    return success_object(serialize_facility(rec))


@bp.route("/atfm/facilities/<facility_id>", methods=["PATCH"])
def patch_facility(facility_id):
    auth_context()
    require_roles(ROLE_SYSTEM_ADMINISTRATOR)
    rec = get_facility(facility_id)
    body = body_json()
    has_rate = "base_acceptance_rate" in body and body["base_acceptance_rate"] is not None
    has_status = "status" in body and body["status"] is not None
    if not has_rate and not has_status:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "PATCH requires at least one of base_acceptance_rate or status",
        )
    if has_rate:
        base_rate = opt_int(body, "base_acceptance_rate")
        if not (FACILITY_BASE_RATE_MIN <= base_rate <= FACILITY_BASE_RATE_MAX):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "base_acceptance_rate must be an integer in [1, 120]",
            )
        rec["base_acceptance_rate"] = base_rate
    if has_status:
        rec["status"] = opt_enum(body, "status", FACILITY_STATUSES)
    touch(rec)
    return success_object(serialize_facility(rec))


@bp.route("/atfm/operators", methods=["POST"])
def create_operator():
    auth_context()
    require_roles(ROLE_SYSTEM_ADMINISTRATOR)
    body = body_json()
    name = req_str(body, "name")
    operator_type = req_enum(body, "operator_type", OPERATOR_TYPES)
    cdm_member = opt_bool(body, "cdm_member", False)
    rec = create_entity(
        "operators",
        {
            "name": name,
            "operator_type": operator_type,
            "cdm_member": cdm_member,
            "cumulative_delay_minutes": 0,
        },
    )
    return success_object(serialize_operator(rec), 201)


@bp.route("/atfm/operators/<operator_id>", methods=["GET"])
def fetch_operator(operator_id):
    auth_context()
    require_roles(*ROLES)
    rec = get_operator(operator_id)
    return success_object(serialize_operator(rec))
