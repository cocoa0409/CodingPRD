"""Applicants and the selection pipeline (application -> review -> decision -> offer)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serialize
import services
import validation
from envelope import ok, paginate, read_json, require_auth, sorted_by_created
from errors import ApiError
from store import (
    APPLICANTS,
    APPLICATIONS,
    DISTRICTS,
    MEMBERS,
    REGIONS,
    now,
    stamp,
    touch,
)
from util import iso, parse_dt

bp = Blueprint("selection", __name__)

APPLICATION_TERMINAL = ("REJECTED", "ACCEPTED")
RESUBMIT_WINDOW_DAYS = 30
OFFER_WINDOW_DAYS = 14
LEADERSHIP_FLOOR = 40.0
SELECT_BAND = 85.00


def _load(application_id):
    application = APPLICATIONS.get(application_id)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND")
    return application


def _guard_terminal(application):
    if application["status"] in APPLICATION_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")


def _owning_applicant(application):
    return APPLICANTS.get(application["applicant_id"])


# --------------------------------------------------------------------------
# Applicants
# --------------------------------------------------------------------------
@bp.route("/corps/applicants", methods=["POST"])
def create_applicant():
    require_auth(["SelectionManager"])
    body = read_json()
    validation.require(
        body,
        "full_name",
        "email",
        "campus_name",
        "campus_tier",
        "graduation_year",
        "leadership_score",
        "achievement_score",
        "gpa",
    )
    full_name = validation.string(body, "full_name")
    email = validation.string(body, "email")
    campus_name = validation.string(body, "campus_name")
    campus_tier = validation.enum(body, "campus_tier", validation.CAMPUS_TIERS)
    graduation_year = validation.integer(body, "graduation_year", minimum=2000)
    leadership = validation.number(body, "leadership_score", minimum=0, maximum=100)
    achievement = validation.number(body, "achievement_score", minimum=0, maximum=100)
    gpa = validation.number(body, "gpa", minimum=0.0, maximum=4.0)
    if any(a["email"] == email for a in APPLICANTS.values()):
        validation.bad("Field 'email' is already held by another applicant.")
    record = {
        "full_name": full_name,
        "email": email,
        "campus_name": campus_name,
        "campus_tier": campus_tier,
        "graduation_year": graduation_year,
        "leadership_score": leadership,
        "achievement_score": achievement,
        "gpa": gpa,
    }
    stamp(record)
    APPLICANTS[record["id"]] = record
    return ok(serialize.applicant(record), 201)


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
@bp.route("/corps/applications", methods=["POST"])
def create_application():
    require_auth(["Applicant", "SelectionManager"])
    body = read_json()
    validation.require(body, "applicant_id", "preferred_region_id", "subject_area", "grade_preference")
    applicant_id = validation.string(body, "applicant_id")
    preferred_region_id = validation.string(body, "preferred_region_id")
    subject_area = validation.enum(body, "subject_area", validation.SUBJECT_AREAS)
    grade_preference = validation.enum(body, "grade_preference", validation.GRADE_BANDS)
    applicant = APPLICANTS.get(applicant_id)
    if applicant is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND")
    live = [
        a
        for a in APPLICATIONS.values()
        if a["applicant_id"] == applicant_id and a["status"] not in ("REJECTED", "DECLINED")
    ]
    if live:
        raise ApiError("ERR_DUPLICATE_APPLICATION")
    record = {
        "applicant_id": applicant_id,
        "preferred_region_id": preferred_region_id,
        "subject_area": subject_area,
        "grade_preference": grade_preference,
        "status": "SUBMITTED",
        "verified_gpa": None,
        "revision_count": 0,
        "selection_score": 0.0,
        "final_selection_score": 0.0,
        "decision_reason": None,
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "offer_expires_at": None,
        "created_corps_member_id": None,
        "returned_at": None,
    }
    stamp(record)
    record["selection_score"] = calc.selection_score(record, applicant, "provisional")
    APPLICATIONS[record["id"]] = record
    return ok(serialize.application(record), 201)


@bp.route("/corps/applications", methods=["GET"])
def list_applications():
    require_auth(["Applicant", "SelectionManager"])
    applicant_id = request.args.get("applicant_id")
    region_id = request.args.get("preferred_region_id")
    rows = sorted_by_created(APPLICATIONS.values())
    if applicant_id:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if region_id:
        rows = [r for r in rows if r["preferred_region_id"] == region_id]
    page, window = paginate(rows)
    return ok([serialize.application(r) for r in page], 200, page=window)


@bp.route("/corps/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    require_auth(["Applicant", "SelectionManager"])
    return ok(serialize.application(_load(application_id)), 200)


@bp.route("/corps/applications/<application_id>/review", methods=["POST"])
def review_application(application_id):
    user_id, _role = require_auth(["SelectionManager"])
    body = read_json()
    verified_gpa = validation.number(body, "verified_gpa", minimum=0.0, maximum=4.0)
    application = _load(application_id)
    _guard_terminal(application)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Review opens only on a SUBMITTED application.")
    applicant = _owning_applicant(application)
    if applicant is None or applicant["leadership_score"] < LEADERSHIP_FLOOR:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The applicant's leadership score is below the program floor for review.",
        )
    application["status"] = "UNDER_REVIEW"
    application["reviewed_by_user_id"] = user_id
    application["verified_gpa"] = verified_gpa
    application["selection_score"] = calc.selection_score(application, applicant, "provisional")
    touch(application)
    return ok(serialize.application(application), 200)


@bp.route("/corps/applications/<application_id>/return", methods=["POST"])
def return_application(application_id):
    require_auth(["SelectionManager"])
    read_json()
    application = _load(application_id)
    _guard_terminal(application)
    if application["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Only an application under review can be returned.")
    if application["revision_count"] >= 3:
        raise ApiError("ERR_INVALID_STATE", "The revision cycle is capped at three returns.")
    application["status"] = "RETURNED_FOR_REVISION"
    application["revision_count"] = application["revision_count"] + 1
    application["returned_at"] = iso(now())
    touch(application)
    return ok(serialize.application(application), 200)


@bp.route("/corps/applications/<application_id>/resubmit", methods=["POST"])
def resubmit_application(application_id):
    user_id, _role = require_auth(["Applicant"])
    read_json()
    application = _load(application_id)
    if user_id != application["applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only the owning applicant may resubmit this application.")
    _guard_terminal(application)
    if application["status"] != "RETURNED_FOR_REVISION":
        raise ApiError("ERR_INVALID_STATE", "Only a returned application can be resubmitted.")
    returned_at = parse_dt(application["returned_at"])
    if now() > returned_at + timedelta(days=RESUBMIT_WINDOW_DAYS):
        raise ApiError("ERR_INVALID_STATE", "The resubmission window has closed.")
    application["status"] = "UNDER_REVIEW"
    application["returned_at"] = None
    touch(application)
    return ok(serialize.application(application), 200)


@bp.route("/corps/applications/<application_id>/decision", methods=["POST"])
def decide_application(application_id):
    user_id, _role = require_auth(["SelectionManager"])
    body = read_json()
    decision = validation.enum(body, "decision", validation.DECISIONS)
    application = _load(application_id)
    _guard_terminal(application)
    if application["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "A decision is recorded only against an application under review.")
    if user_id == application["reviewed_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", "The deciding operator must differ from the reviewing operator.")
    applicant = _owning_applicant(application)
    final_score = calc.selection_score(application, applicant, "final")
    if decision == "SELECT" and final_score < SELECT_BAND:
        raise ApiError("ERR_SCORE_BELOW_THRESHOLD")
    application["final_selection_score"] = final_score
    application["decided_by_user_id"] = user_id
    application["decision_reason"] = body.get("decision_reason")
    application["status"] = "SELECTED" if decision == "SELECT" else "REJECTED"
    touch(application)
    return ok(serialize.application(application), 200)


@bp.route("/corps/applications/<application_id>/offer", methods=["POST"])
def extend_offer(application_id):
    require_auth(["SelectionManager"])
    read_json()
    application = _load(application_id)
    _guard_terminal(application)
    if application["status"] not in ("SELECTED", "DECLINED"):
        raise ApiError("ERR_INVALID_STATE", "An offer may be extended to a SELECTED or DECLINED application.")
    has_active_district = any(
        d["region_id"] == application["preferred_region_id"] and d["agreement_status"] == "ACTIVE"
        for d in DISTRICTS.values()
    )
    if not has_active_district:
        raise ApiError("ERR_DISTRICT_NOT_ACTIVE")
    application["status"] = "OFFER_EXTENDED"
    application["offer_expires_at"] = iso(now() + timedelta(days=OFFER_WINDOW_DAYS))
    touch(application)
    return ok(serialize.application(application), 200)


@bp.route("/corps/applications/<application_id>/offer/respond", methods=["POST"])
def respond_to_offer(application_id):
    user_id, _role = require_auth(["Applicant"])
    body = read_json()
    accept = validation.boolean(body, "accept")
    application = _load(application_id)
    if user_id != application["applicant_id"]:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Only the owning applicant may answer this offer.")
    if application["status"] != "OFFER_EXTENDED":
        raise ApiError("ERR_INVALID_STATE", "There is no outstanding offer to answer.")
    if not accept:
        application["status"] = "DECLINED"
        application["offer_expires_at"] = None
        touch(application)
        return ok(serialize.application(application), 200)

    if now() > parse_dt(application["offer_expires_at"]):
        raise ApiError("ERR_OFFER_EXPIRED")
    region = REGIONS.get(application["preferred_region_id"])
    if region is not None:
        committed = 0
        for member in MEMBERS.values():
            owning = APPLICATIONS.get(member["application_id"])
            if (
                owning is not None
                and owning["preferred_region_id"] == application["preferred_region_id"]
                and member["service_status"] in ("ACTIVE", "ON_LEAVE")
            ):
                committed += 1
        if committed >= region["max_corps_members"]:
            raise ApiError("ERR_INVALID_STATE", "The region's corps member quota is exhausted.")

    application["status"] = "ACCEPTED"
    member = services.synthesize_member(application, region)
    application["created_corps_member_id"] = member["id"]
    touch(application)
    return ok(serialize.application(application), 200)
