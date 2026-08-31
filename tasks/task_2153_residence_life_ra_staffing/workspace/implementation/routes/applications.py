"""RA recruitment, training, certification and employment."""
from flask import Blueprint, g

import derive
import responses
import services
import store
import validators as V
from auth import endpoint, require_owner
from constants import (
    API_PREFIX, CERTIFICATION_CREDIT_MIN, MANDATORY_MODULE_CODES,
    MAX_REVISION_ROUNDS, MODULE_CODES, MODULE_CREDITS,
)
from errors import ApiError

DIRECTOR = ["ResidenceDirector"]
STUDENT = ["Student"]
bp = Blueprint("applications", __name__)


@bp.route("%s/ra-applications" % API_PREFIX, methods=["POST"])
@endpoint(["Student", "ResidenceDirector"])
def create_application():
    body = V.body()
    applicant_id = V.s_id(body, "applicant_student_id")
    term_code = V.s_str(body, "term_code", pattern=r"^[0-9]{4}(FA|SP|SU)$")
    essay_ref = V.s_str(body, "essay_ref")
    student = store.get("students", applicant_id)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    for other in store.all_rows("applications"):
        if other["applicant_student_id"] == applicant_id and other["term_code"] == term_code:
            raise ApiError("ERR_DUPLICATE_APPLICATION")
    row = store.insert("applications", "RAApplication", {
        "applicant_student_id": applicant_id,
        "term_code": term_code,
        "essay_ref": essay_ref,
        "status": "DRAFT",
        "interview_score": None,
        "revision_count": 0,
        "revision_notes": None,
        "reviewed_by_user_id": None,
        "submitted_at": None,
        "created_ra_id": None,
    })
    return responses.obj(row, 201)


@bp.route("%s/ra-applications/<application_id>/submit" % API_PREFIX, methods=["POST"])
@endpoint(STUDENT)
def submit_application(application_id):
    app_row = V.must_get("RAApplication", application_id)
    require_owner(app_row["applicant_student_id"])
    body = V.body()
    essay_ref = V.s_str(body, "essay_ref", required=False)
    if app_row["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if essay_ref is not None:
        app_row["essay_ref"] = essay_ref
    if not (app_row["essay_ref"] or "").strip():
        raise ApiError("ERR_INVALID_REQUEST", "essay_ref must be non-empty.")
    app_row["status"] = "SUBMITTED"
    app_row["submitted_at"] = store.now_iso()
    return responses.obj(app_row)


@bp.route("%s/ra-applications/<application_id>/review" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def review_application(application_id):
    app_row = V.must_get("RAApplication", application_id)
    body = V.body()
    score = V.s_num(body, "interview_score", 0, 100)
    if app_row["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    app_row["status"] = "UNDER_REVIEW"
    app_row["interview_score"] = score
    app_row["reviewed_by_user_id"] = g.user_id
    return responses.obj(app_row)


@bp.route("%s/ra-applications/<application_id>/decision" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def decide_application(application_id):
    app_row = V.must_get("RAApplication", application_id)
    body = V.body()
    decision = V.s_enum(body, "decision", ("REQUEST_REVISION", "OFFER", "REJECT"))
    notes = V.s_str(body, "revision_notes", required=False)
    if app_row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if decision == "REQUEST_REVISION":
        if app_row["revision_count"] >= MAX_REVISION_ROUNDS:
            raise ApiError("ERR_REVISION_LIMIT_REACHED")
        app_row["revision_count"] += 1
        app_row["revision_notes"] = notes
        app_row["status"] = "REVISION_REQUESTED"
    elif decision == "OFFER":
        if app_row["interview_score"] is None:
            raise ApiError("ERR_APPLICATION_STATE_INVALID")
        app_row["status"] = "OFFERED"
    else:
        app_row["status"] = "REJECTED"
    return responses.obj(app_row)


@bp.route("%s/ra-applications/<application_id>/response" % API_PREFIX, methods=["POST"])
@endpoint(STUDENT)
def respond_application(application_id):
    app_row = V.must_get("RAApplication", application_id)
    require_owner(app_row["applicant_student_id"])
    body = V.body()
    response = V.s_enum(body, "response", ("ACCEPT", "DECLINE"))
    if app_row["status"] != "OFFERED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    if response == "DECLINE":
        app_row["status"] = "DECLINED"
        return responses.obj(app_row)
    ra = store.insert("ras", "RA", {
        "student_id": app_row["applicant_student_id"],
        "application_id": app_row["id"],
        "assigned_floor_id": None,
        "employment_status": "PROVISIONAL",
        "certification_status": "UNCERTIFIED",
        "completed_module_codes": [],
        "certified_at": None,
        "separation_reason": None,
    })
    app_row["status"] = "ACCEPTED"
    app_row["created_ra_id"] = ra["id"]
    return responses.obj(app_row)


# --------------------------------------------------------------------- RA
@bp.route("%s/ras/<ra_id>/floor-assignment" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def assign_floor(ra_id):
    ra = V.must_get("RA", ra_id)
    body = V.body()
    floor_id = V.s_id(body, "floor_id")
    floor = store.get("floors", floor_id)
    if floor is None:
        raise ApiError("ERR_FLOOR_NOT_FOUND")
    ra["assigned_floor_id"] = floor_id
    return responses.obj(ra)


@bp.route("%s/ras/<ra_id>/training-records" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def training_record(ra_id):
    ra = V.must_get("RA", ra_id)
    body = V.body()
    code = V.s_enum(body, "module_code", MODULE_CODES)
    if ra["certification_status"] != "IN_TRAINING":
        raise ApiError("ERR_RA_STATE_INVALID")
    if code in ra["completed_module_codes"]:
        raise ApiError("ERR_MODULE_ALREADY_COMPLETED")
    ra["completed_module_codes"] = list(ra["completed_module_codes"]) + [code]
    return responses.obj(ra)


@bp.route("%s/ras/<ra_id>/certification" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def certification(ra_id):
    ra = V.must_get("RA", ra_id)
    body = V.body()
    action = V.s_enum(body, "action", ("START_TRAINING", "CERTIFY", "LAPSE"))
    status = ra["certification_status"]
    if action == "START_TRAINING":
        if status not in ("UNCERTIFIED", "LAPSED"):
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["certification_status"] = "IN_TRAINING"
    elif action == "CERTIFY":
        if status != "IN_TRAINING":
            raise ApiError("ERR_RA_STATE_INVALID")
        if derive.ra_credits(ra) < CERTIFICATION_CREDIT_MIN:
            raise ApiError("ERR_TRAINING_CREDITS_INSUFFICIENT")
        for code in MANDATORY_MODULE_CODES:
            if code not in ra["completed_module_codes"]:
                raise ApiError("ERR_MANDATORY_MODULE_MISSING")
        ra["certification_status"] = "CERTIFIED"
        ra["certified_at"] = store.now_iso()
    else:
        if status != "CERTIFIED":
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["certification_status"] = "LAPSED"
    return responses.obj(ra)


@bp.route("%s/ras/<ra_id>/employment" % API_PREFIX, methods=["POST"])
@endpoint(DIRECTOR)
def employment(ra_id):
    ra = V.must_get("RA", ra_id)
    body = V.body()
    action = V.s_enum(body, "action", ("ACTIVATE", "SUSPEND", "REINSTATE", "SEPARATE"))
    reason = V.s_str(body, "reason", required=False)
    status = ra["employment_status"]
    if action == "ACTIVATE":
        if status != "PROVISIONAL" or not ra.get("assigned_floor_id"):
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["employment_status"] = "ACTIVE"
    elif action == "SUSPEND":
        if status != "ACTIVE":
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["employment_status"] = "SUSPENDED"
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["employment_status"] = "ACTIVE"
    else:
        if status not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_RA_STATE_INVALID")
        ra["employment_status"] = "SEPARATED"
        ra["separation_reason"] = reason
        services.separate_ra_cascade(ra)
    return responses.obj(ra)
