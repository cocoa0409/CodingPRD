"""EnforcementCase endpoints (PRD §3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calculations as calc
from db import STORE, bump, get_clock, new_entity
from errors import api_err
from helpers import get_body, opt_str, req_enum, req_number, req_str
from middleware import require_roles
from response import apply_filters, list_response, success_obj
from serialization import case_out

bp = Blueprint("enforcement", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")
RESOLUTION_TRACKS = ("RESTORATION", "AFTER_THE_FACT_PERMIT")


def _get_case_or_404(case_id):
    case = STORE["cases"].get(case_id)
    if case is None:
        raise api_err("ERR_CASE_NOT_FOUND",
                      "No EnforcementCase with id %s" % case_id)
    return case


@bp.post("/wetland-permits/enforcement-cases")
def create_case():
    user_id, role = require_roles(["EnforcementOfficer"])
    body = get_body()
    # Tier 5: body FK existence.
    site_id = req_str(body, "site_id")
    if site_id not in STORE["sites"]:
        raise api_err("ERR_SITE_NOT_FOUND", "No WatersSite with id %s" % site_id)
    responsible_id = req_str(body, "responsible_applicant_id")
    if responsible_id not in STORE["applicants"]:
        raise api_err("ERR_APPLICANT_NOT_FOUND",
                      "No Applicant with id %s" % responsible_id)
    # Tier 6: shape. PRD §3.9 allows zero or more fill acres on a manual
    # case ("the unauthorized_fill_acres (zero or more)").
    fill_acres = req_number(body, "unauthorized_fill_acres",
                            minimum=Decimal("0"))
    description = req_str(body, "description")
    case = new_entity({
        "site_id": site_id,
        "responsible_applicant_id": responsible_id,
        "unauthorized_fill_acres": fill_acres,
        "description": description,
        "case_source": "MANUAL",
        "opened_by_officer_id": user_id,
        "opened_date": get_clock(),
        "confirmed_date": None,
        "penalty_final_dollars": None,
        "resolution_track": "NONE",
        "atf_application_id": None,
        "restoration_deadline": None,
        "extension_used": False,
        "case_status": "OPENED",
    })
    STORE["cases"][case["id"]] = case
    return success_obj(case_out(case), 201)


@bp.get("/wetland-permits/enforcement-cases")
def list_cases():
    require_roles(list(ALL_ROLES))
    cases = apply_filters(STORE["cases"].values(), {
        "site_id": "site_id",
        "responsible_applicant_id": "responsible_applicant_id",
        "atf_application_id": "atf_application_id",
        "case_status": "case_status",
    })
    return list_response(cases, case_out)


@bp.get("/wetland-permits/enforcement-cases/<id>")
def get_case(id):
    require_roles(list(ALL_ROLES))
    return success_obj(case_out(_get_case_or_404(id)))


@bp.post("/wetland-permits/enforcement-cases/<id>/confirm-violation")
def confirm_violation(id):
    user_id, role = require_roles(["EnforcementOfficer"])
    case = _get_case_or_404(id)
    get_body()
    # Tier 7: state.
    if case["case_status"] != "OPENED":
        raise api_err("ERR_CASE_INVALID_STATE",
                      "confirm-violation requires an OPENED case")
    # Priority 14: segregation of duties — the confirming officer must
    # differ from the officer who opened the case.
    if user_id == case["opened_by_officer_id"]:
        raise api_err("ERR_SEGREGATION_OF_DUTIES",
                      "The officer who opened the case may not confirm it")
    case["case_status"] = "VIOLATION_CONFIRMED"
    case["confirmed_date"] = get_clock()
    bump(case)
    return success_obj(case_out(case))


@bp.post("/wetland-permits/enforcement-cases/<id>/set-resolution")
def set_resolution(id):
    require_roles(["EnforcementOfficer"])
    case = _get_case_or_404(id)
    body = get_body()
    track = body.get("track")
    # Tier 5: a present atf_application_id on the ATF track must reference
    # an existing application.
    atf_application = None
    atf_application_id = body.get("atf_application_id")
    if track == "AFTER_THE_FACT_PERMIT" and atf_application_id is not None:
        if not isinstance(atf_application_id, str):
            raise api_err("ERR_INVALID_REQUEST",
                          "Field atf_application_id must be a string")
        atf_application = STORE["applications"].get(atf_application_id)
        if atf_application is None:
            raise api_err("ERR_APPLICATION_NOT_FOUND",
                          "No PermitApplication with id %s"
                          % atf_application_id)
    # Tier 6: shape.
    track = req_enum(body, "track", RESOLUTION_TRACKS)
    if track == "AFTER_THE_FACT_PERMIT" and atf_application_id is None:
        raise api_err("ERR_INVALID_REQUEST",
                      "atf_application_id is required on the "
                      "AFTER_THE_FACT_PERMIT track")
    # Tier 7: state.
    if case["case_status"] != "VIOLATION_CONFIRMED":
        raise api_err("ERR_CASE_INVALID_STATE",
                      "set-resolution requires a VIOLATION_CONFIRMED case")
    clock = get_clock()
    if track == "RESTORATION":
        case["resolution_track"] = "RESTORATION"
        case["restoration_deadline"] = clock + timedelta(
            days=calc.RESTORATION_DEADLINE_DAYS)
    else:
        # Priority 21: two-way linkage — the application's
        # enforcement_case_id must name this case.
        if atf_application["enforcement_case_id"] != case["id"]:
            raise api_err("ERR_CASE_INVALID_STATE",
                          "The named application's enforcement_case_id does "
                          "not reference this case")
        case["resolution_track"] = "AFTER_THE_FACT_PERMIT"
        case["atf_application_id"] = atf_application["id"]
    case["case_status"] = "RESOLUTION_PENDING"
    bump(case)
    return success_obj(case_out(case))


@bp.post("/wetland-permits/enforcement-cases/<id>/verify-restoration")
def verify_restoration(id):
    require_roles(["EnforcementOfficer"])
    case = _get_case_or_404(id)
    get_body()
    # Tier 7: defined only for a RESOLUTION_PENDING case on the RESTORATION
    # track.
    if case["case_status"] != "RESOLUTION_PENDING" \
            or case["resolution_track"] != "RESTORATION":
        raise api_err("ERR_CASE_INVALID_STATE",
                      "verify-restoration requires a RESOLUTION_PENDING "
                      "case on the RESTORATION track")
    # Timely restoration earns the good-faith offset: half the accrued
    # penalty, rounded half-up to cents at fixation.
    accrued = calc.penalty_accrued(case)
    case["penalty_final_dollars"] = calc.q2(
        accrued * calc.RESTORATION_GOOD_FAITH_OFFSET)
    case["case_status"] = "CLOSED"
    bump(case)
    return success_obj(case_out(case))


@bp.post("/wetland-permits/enforcement-cases/<id>/grant-extension")
def grant_extension(id):
    require_roles(["DistrictEngineer"])
    case = _get_case_or_404(id)
    get_body()
    # Tier 7: state.
    if case["case_status"] != "DEFAULTED":
        raise api_err("ERR_CASE_INVALID_STATE",
                      "grant-extension requires a DEFAULTED case")
    # One extension maximum.
    if case["extension_used"]:
        raise api_err("ERR_EXTENSION_ALREADY_USED",
                      "The one-time extension has already been used")
    case["restoration_deadline"] = get_clock() + timedelta(
        days=calc.EXTENSION_DAYS)
    case["extension_used"] = True
    case["case_status"] = "RESOLUTION_PENDING"
    bump(case)
    return success_obj(case_out(case))
