"""Reference data: deferral agencies, employers, complainants (PRD 3.1)."""

from flask import Blueprint

import constants
import serializers
from domain import remedy, screening
from errors import (
    ApiError,
    ERR_DUPLICATE_AGENCY_STATE,
    ERR_EMPLOYER_NOT_FOUND,
)
from helpers import (
    authenticate,
    bump,
    common_fields,
    request_body,
    require_roles,
    respond_object,
)
from store import db
from validation import opt_int, opt_string, req_bool, req_enum, req_int, req_string

bp = Blueprint("reference", __name__, url_prefix="/eeoc")


@bp.post("/deferral-agencies")
def create_deferral_agency():
    _, role = authenticate()
    require_roles(role, (constants.ROLE_PLATFORM_ADMIN,))
    body = request_body()
    state_code = req_string(body, "state_code")
    agency_name = req_string(body, "agency_name")
    filing_deadline_days = req_int(
        body, "filing_deadline_days", choices=constants.AGENCY_DEADLINE_CHOICES
    )
    work_sharing_policy = req_enum(
        body, "work_sharing_policy", constants.WORK_SHARING_POLICIES
    )
    covers_age = req_bool(body, "covers_age")

    # One agency per state_code.
    for existing in db.deferral_agencies.values():
        if existing["state_code"] == state_code:
            raise ApiError(
                ERR_DUPLICATE_AGENCY_STATE,
                "A deferral agency already exists for state %s." % state_code,
            )

    agency = {
        **common_fields(),
        "state_code": state_code,
        "agency_name": agency_name,
        "filing_deadline_days": filing_deadline_days,
        "work_sharing_policy": work_sharing_policy,
        "covers_age": covers_age,
    }
    db.deferral_agencies[agency["id"]] = agency
    return respond_object(serializers.serialize_deferral_agency(agency), status=201)


@bp.post("/employers")
def create_employer():
    _, role = authenticate()
    require_roles(role, (constants.ROLE_INTAKE_OFFICER,))
    body = request_body()
    legal_name = req_string(body, "legal_name")
    state_code = req_string(body, "state_code")
    employee_count_current = req_int(body, "employee_count_current", minimum=0)

    employer = {
        **common_fields(),
        "legal_name": legal_name,
        "state_code": state_code,
        "employee_count_current": employee_count_current,
        "size_band": screening.size_band_for_count(employee_count_current),
    }
    db.employers[employer["id"]] = employer
    return respond_object(serializers.serialize_employer(employer), status=201)


@bp.patch("/employers/<employer_id>")
def update_employer(employer_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_INTAKE_OFFICER,))
    body = request_body()
    legal_name, has_legal_name = opt_string(body, "legal_name")
    employee_count_current, has_count = opt_int(
        body, "employee_count_current", minimum=0
    )

    employer = db.employers.get(employer_id)
    if employer is None:
        raise ApiError(ERR_EMPLOYER_NOT_FOUND, "No employer with the given id.")

    if has_legal_name:
        employer["legal_name"] = legal_name
    if has_count:
        employer["employee_count_current"] = employee_count_current
    # size_band is recomputed on every PATCH.
    employer["size_band"] = screening.size_band_for_count(
        employer["employee_count_current"]
    )
    bump(employer)

    # Re-band PROVISIONAL remedy packages on this employer's non-terminal
    # conciliations (each keeps its original projection_date).
    remedy.revalue_provisional_packages_for_employer(employer)

    return respond_object(serializers.serialize_employer(employer), status=200)


@bp.post("/complainants")
def create_complainant():
    _, role = authenticate()
    require_roles(role, (constants.ROLE_INTAKE_OFFICER,))
    body = request_body()
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")

    complainant = {
        **common_fields(),
        "full_name": full_name,
        "email": email,
    }
    db.complainants[complainant["id"]] = complainant
    return respond_object(
        serializers.serialize_complainant(complainant), status=201
    )
