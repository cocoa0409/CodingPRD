"""Grant program and application routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_GRANT_BUDGET_EXCEEDED,
                    ERR_GRANT_SCORE_TOO_LOW, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_UNAUTHORIZED)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, check_occ)
from middleware import require_roles
from response import success_object

bp = Blueprint("grants", __name__)


@bp.post("/wiki/grant-programs")
def create_program():
    require_roles("GrantAdministrator")
    body = get_body()
    require_fields(body, ["name", "fiscal_year", "budget_cents"])
    try:
        fiscal_year = int(body["fiscal_year"])
        budget = int(body["budget_cents"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "fiscal_year and budget_cents must be integers", 400)
    p = base_entity()
    p.update({
        "name": body["name"],
        "fiscal_year": fiscal_year,
        "budget_cents": budget,
        "allocated_cents": 0,
        "status": "OPEN",
    })
    db.grant_programs[p["id"]] = p
    return success_object(p, status=201)


@bp.get("/wiki/grant-programs")
def list_programs():
    require_roles("GrantAdministrator", "GrantReviewer", "VolunteerEditor",
                  "PlatformAdmin")
    return list_response(db.grant_programs, filters={
        "status": request.args.get("status"),
        "fiscal_year": request.args.get("fiscal_year"),
    })


@bp.get("/wiki/grant-programs/<programId>")
def get_program(programId):
    require_roles("GrantAdministrator", "GrantReviewer", "VolunteerEditor")
    return success_object(lookup(db.grant_programs, programId, "Grant program"))


@bp.post("/wiki/grant-programs/<programId>/close")
def close_program(programId):
    require_roles("GrantAdministrator")
    p = lookup(db.grant_programs, programId, "Grant program")
    body = get_body()
    check_occ(body, "expected_program_version", p)
    if p["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an OPEN program can be closed", 409)
    p["status"] = "CLOSED"
    touch(p)
    return success_object(p)


@bp.post("/wiki/grant-programs/<programId>/applications")
def create_application(programId):
    user_id, _role = require_roles("VolunteerEditor")
    program = lookup(db.grant_programs, programId, "Grant program")
    if program["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "Applications may only be submitted to an OPEN program",
                       409)
    body = get_body()
    require_fields(body, ["project_title", "requested_cents"])
    try:
        requested = int(body["requested_cents"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "requested_cents must be an integer", 400)
    a = base_entity()
    a.update({
        "program_id": program["id"],
        "applicant_id": user_id,
        "project_title": body["project_title"],
        "requested_cents": requested,
        "status": "SUBMITTED",
        "review_score": None,
        "awarded_cents": None,
    })
    db.grant_applications[a["id"]] = a
    return success_object(a, status=201)


@bp.get("/wiki/grant-applications")
def list_applications():
    require_roles("GrantAdministrator", "GrantReviewer", "VolunteerEditor",
                  "PlatformAdmin")
    return list_response(db.grant_applications, filters={
        "program_id": request.args.get("program_id"),
        "applicant_id": request.args.get("applicant_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/grant-applications/<applicationId>")
def get_application(applicationId):
    require_roles("GrantAdministrator", "GrantReviewer", "VolunteerEditor")
    return success_object(lookup(db.grant_applications, applicationId,
                                 "Grant application"))


@bp.post("/wiki/grant-applications/<applicationId>/start-review")
def start_review(applicationId):
    require_roles("GrantReviewer")
    a = lookup(db.grant_applications, applicationId, "Grant application")
    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a SUBMITTED application can enter review", 409)
    program = db.grant_programs.get(a["program_id"])
    if program is None or program["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE,
                       "GrantProgram must be OPEN to start review", 409)
    a["status"] = "UNDER_REVIEW"
    touch(a)
    return success_object(a)


def _sub_score(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {name}",
                       400)
    try:
        v = int(body[name])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, f"{name} must be an integer", 400)
    if v < 0 or v > 100:
        raise ApiError(ERR_INVALID_REQUEST,
                       f"{name} must be between 0 and 100", 400)
    return v


@bp.post("/wiki/grant-applications/<applicationId>/score")
def score_application(applicationId):
    require_roles("GrantReviewer")
    a = lookup(db.grant_applications, applicationId, "Grant application")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_REVIEW application can be scored", 409)
    body = get_body()
    impact = _sub_score(body, "impact_score")
    feasibility = _sub_score(body, "feasibility_score")
    budget = _sub_score(body, "budget_reasonableness_score")
    community = _sub_score(body, "community_support_score")
    raw = (Decimal("0.3") * impact + Decimal("0.3") * feasibility
           + Decimal("0.2") * budget + Decimal("0.2") * community)
    a["review_score"] = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    touch(a)
    return success_object(a)


@bp.post("/wiki/grant-applications/<applicationId>/approve")
def approve_application(applicationId):
    require_roles("GrantReviewer")
    a = lookup(db.grant_applications, applicationId, "Grant application")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_REVIEW application can be approved", 409)
    body = get_body()
    require_fields(body, ["awarded_cents"])
    check_occ(body, "expected_application_version", a)
    try:
        awarded = int(body["awarded_cents"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "awarded_cents must be an integer", 400)
    if awarded <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "awarded_cents must be greater than zero", 400)
    if a["review_score"] is None or a["review_score"] < 70:
        raise ApiError(ERR_GRANT_SCORE_TOO_LOW,
                       "Review score below 70 threshold for approval", 409)
    program = lookup(db.grant_programs, a["program_id"], "Grant program")
    if program["allocated_cents"] + awarded > program["budget_cents"]:
        raise ApiError(ERR_GRANT_BUDGET_EXCEEDED,
                       "Award would exceed grant program budget", 409)
    a["status"] = "APPROVED"
    a["awarded_cents"] = awarded
    touch(a)
    program["allocated_cents"] += awarded
    touch(program)
    return success_object(a)


@bp.post("/wiki/grant-applications/<applicationId>/reject")
def reject_application(applicationId):
    require_roles("GrantReviewer")
    a = lookup(db.grant_applications, applicationId, "Grant application")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an UNDER_REVIEW application can be rejected", 409)
    a["status"] = "REJECTED"
    touch(a)
    return success_object(a)


@bp.post("/wiki/grant-applications/<applicationId>/withdraw")
def withdraw_application(applicationId):
    user_id, _role = require_roles("VolunteerEditor")
    a = lookup(db.grant_applications, applicationId, "Grant application")
    if a["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE,
                       "Only a SUBMITTED or UNDER_REVIEW application can be "
                       "withdrawn", 409)
    if a["applicant_id"] != user_id:
        raise ApiError(ERR_UNAUTHORIZED,
                       "Only the applicant may withdraw an application", 403)
    a["status"] = "WITHDRAWN"
    touch(a)
    return success_object(a)
