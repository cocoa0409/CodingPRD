"""Counseling sessions and treatment plan reviews."""
from flask import Blueprint, request

import db
from constants import SESSION_TYPES
from errors import ApiError
from response import ok_array_paged, ok_object, paginate_sorted, parse_pagination
from routes.common import context, path_patient
from services import counseling, entity
from validation import bool_field, datetime_field, int_field, text_field

bp = Blueprint("counseling", __name__)

READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "Counselor",
    "MedicalDirector",
    "RegulatoryAuditor",
]
REVIEW_READ_ROLES = [
    "ProgramAdministrator",
    "Physician",
    "Nurse",
    "MedicalDirector",
    "RegulatoryAuditor",
]


@bp.route("/otp/counseling-sessions", methods=["POST"])
def create_session():
    actor = context(["Counselor", "ProgramAdministrator"])
    body = request.get_json(silent=True) or {}
    patient = path_patient(text_field(body, "patient_id"))
    session_type = text_field(body, "session_type")
    if session_type not in SESSION_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "session_type must be INDIVIDUAL, GROUP or FAMILY")
    duration = int_field(body, "duration_minutes")
    if duration < 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must not be negative")
    counselor_staff_id = body.get("counselor_staff_id")
    if counselor_staff_id is not None:
        counselor_staff_id = str(counselor_staff_id).strip()
    if not counselor_staff_id:
        counselor_staff_id = actor.user_id
    row = counseling.create_session(
        patient,
        session_type,
        datetime_field(body, "scheduled_datetime"),
        duration,
        counselor_staff_id,
    )
    return ok_object(entity.serialize_session(row), 201)


@bp.route("/otp/counseling-sessions", methods=["GET"])
def list_sessions():
    context(READ_ROLES)
    rows = list(db.counseling_sessions.values())
    for name in ("patient_id", "program_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_session(r) for r in page], limit, offset, total)


@bp.route("/otp/counseling-sessions/<session_id>", methods=["GET"])
def read_session(session_id):
    context(READ_ROLES)
    row = counseling.session_of(session_id)
    return ok_object(entity.serialize_session(row))


@bp.route("/otp/counseling-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    actor = context(["Counselor"])
    row = counseling.session_of(session_id)
    body = request.get_json(silent=True) or {}
    counseling.complete_session(row, int_field(body, "attended_minutes"), actor)
    return ok_object(entity.serialize_session(row))


@bp.route("/otp/counseling-sessions/<session_id>/no-show", methods=["POST"])
def no_show(session_id):
    actor = context(["Counselor"])
    row = counseling.session_of(session_id)
    counseling.no_show(row, actor)
    return ok_object(entity.serialize_session(row))


# ---------------------------------------------------------------------------
# Treatment plan reviews
# ---------------------------------------------------------------------------
@bp.route("/otp/treatment-plan-reviews", methods=["POST"])
def create_review():
    actor = context(["Physician", "MedicalDirector"])
    body = request.get_json(silent=True) or {}
    patient = path_patient(text_field(body, "patient_id"))
    reviewer = text_field(body, "reviewer_physician_id")
    row = counseling.create_review(
        patient,
        reviewer,
        datetime_field(body, "reviewed_at"),
        bool_field(body, "signed_off", True),
    )
    _ = actor
    return ok_object(entity.serialize_review(row), 201)


@bp.route("/otp/treatment-plan-reviews", methods=["GET"])
def list_reviews():
    context(REVIEW_READ_ROLES)
    rows = list(db.treatment_plan_reviews.values())
    for name in ("patient_id", "program_id", "reviewer_physician_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    limit, offset = parse_pagination(request.args)
    page, total = paginate_sorted(rows, limit, offset)
    return ok_array_paged([entity.serialize_review(r) for r in page], limit, offset, total)


@bp.route("/otp/treatment-plan-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    context(["ProgramAdministrator", "Physician", "MedicalDirector", "RegulatoryAuditor"])
    row = counseling.review_of(review_id)
    return ok_object(entity.serialize_review(row))