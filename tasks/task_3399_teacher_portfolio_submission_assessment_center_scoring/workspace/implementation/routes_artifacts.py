"""Artifact endpoints (PRD 3.3): upload to an open portfolio attempt, list."""
from flask import Blueprint

import constants as C
import errors as E
import serializers as ser
from response import ok, ok_list
from routes_submissions import _get_submission_or_404, _assessor_holds_assignment
from store import DB, new_id, next_seq, now
from validation import (auth_headers, require_role, body, req_field,
                        as_number, as_int, pagination_params, paginate)

bp = Blueprint("artifacts", __name__)

_ARTIFACT_TYPES = ("VIDEO", "STUDENT_WORK", "WRITTEN_COMMENTARY", "RELEASE_FORM")
_FORMATS = {
    "VIDEO": ("mp4", "mov"),
    "STUDENT_WORK": ("pdf", "docx"),
    "WRITTEN_COMMENTARY": ("pdf", "docx"),
    "RELEASE_FORM": ("pdf", "docx"),
}


@bp.post("/submissions/<submission_id>/artifacts")
def upload_artifact(submission_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    sub = _get_submission_or_404(submission_id)
    if sub["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may upload artifacts only to their own submissions")
    if sub["status"] not in ("IN_PROGRESS", "RETURNED"):
        E.fail(E.ERR_SUBMISSION_NOT_SUBMITTABLE, 409,
               "Artifacts upload only while the attempt is IN_PROGRESS or RETURNED")
    data = body()
    artifact_type = req_field(data, "artifact_type")
    file_format = req_field(data, "file_format")
    file_size_mb = as_number(req_field(data, "file_size_mb"), "file_size_mb")
    if artifact_type not in _ARTIFACT_TYPES:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "artifact_type must be one of VIDEO, STUDENT_WORK, "
               "WRITTEN_COMMENTARY, RELEASE_FORM")
    duration = data.get("duration_minutes")
    if artifact_type == "VIDEO":
        if duration is None:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "duration_minutes is required for VIDEO artifacts")
        duration = as_number(duration, "duration_minutes")
    elif duration is not None:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "duration_minutes is only allowed for VIDEO artifacts")
    student_count = data.get("subject_student_count")
    if student_count is not None:
        student_count = as_int(student_count, "subject_student_count")
        if student_count < 1:
            E.fail(E.ERR_INVALID_REQUEST, 400,
                   "subject_student_count must be at least 1 when supplied")
    if file_format not in _FORMATS[artifact_type]:
        E.fail(E.ERR_ARTIFACT_FORMAT_INVALID, 422,
               "file_format %s is not allowed for %s" % (file_format, artifact_type))
    size_limit = C.VIDEO_MAX_MB if artifact_type == "VIDEO" else C.DOC_MAX_MB
    if file_size_mb > size_limit:
        E.fail(E.ERR_ARTIFACT_SIZE_EXCEEDED, 422,
               "file_size_mb exceeds the %s MB limit for %s"
               % (size_limit, artifact_type))
    if artifact_type == "VIDEO" and duration > C.VIDEO_MAX_MINUTES:
        E.fail(E.ERR_VIDEO_DURATION_EXCEEDED, 422,
               "VIDEO duration_minutes must be at most %s" % C.VIDEO_MAX_MINUTES)
    artifact = {
        "id": new_id(),
        "submission_id": sub["id"],
        "artifact_type": artifact_type,
        "file_format": file_format,
        "file_size_mb": file_size_mb,
        "duration_minutes": duration,
        "subject_student_count": student_count,
        "created_at": now(),
        "_seq": next_seq(),
    }
    DB.artifacts[artifact["id"]] = artifact
    return ok(ser.artifact(artifact), 201)


@bp.get("/submissions/<submission_id>/artifacts")
def list_artifacts(submission_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_ASSESSOR,
                        C.ROLE_SCORING_ADMIN, C.ROLE_BOARD_ADMIN])
    sub = _get_submission_or_404(submission_id)
    if role == C.ROLE_CANDIDATE and sub["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own artifacts")
    if role == C.ROLE_ASSESSOR and not _assessor_holds_assignment(uid, sub["id"]):
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Assessors may read artifacts only while holding an assignment")
    limit, offset = pagination_params()
    items = [a for a in DB.artifacts.values() if a["submission_id"] == sub["id"]]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.artifact(a) for a in page], limit, offset, total)
