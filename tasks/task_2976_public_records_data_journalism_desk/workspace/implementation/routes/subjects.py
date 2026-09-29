"""SubjectResponseRequest endpoints -- the right-of-reply process (PRD section 3.9)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import ALL_ROLES, ROLE_RECORDS_COORDINATOR, authenticate

bp = Blueprint("subjects", __name__)

CONTACT_CHANNELS = ("EMAIL", "PHONE", "CERTIFIED_MAIL", "IN_PERSON")
MIN_NOTICE_HOURS = 72
MIN_DOCUMENTED_ATTEMPTS = 2
ATTEMPT_FORBIDDEN_STATUSES = ("DRAFT", "RESPONDED", "UNREACHABLE")
RESPONDABLE_STATUSES = ("NOTICE_SENT", "NO_RESPONSE")


def _invalid_subject_state(record):
    return ApiError(
        "ERR_INVALID_SUBJECT_STATE",
        "The operation is not declared from subject-response status %s." % record["status"],
    )


@bp.post("/subject-response-requests")
def create_subject_request():
    authenticate([ROLE_RECORDS_COORDINATOR])
    payload = v.body()
    investigation_id = v.field_string(payload, "investigation_id", min_len=1, non_blank=True)
    subject_name = v.field_string(payload, "subject_name", min_len=1, max_len=160,
                                  non_blank=True)
    contact_channel = v.field_enum(payload, "contact_channel", CONTACT_CHANNELS)
    db.get_investigation(investigation_id)
    record = db.insert("subject_response_requests", {
        "investigation_id": investigation_id,
        "subject_name": subject_name,
        "contact_channel": contact_channel,
        "status": "DRAFT",
        "attempt_count": 0,
        "documented_attempts": [],
        "notice_sent_at": None,
        "response_deadline_at": None,
        "response_text": None,
        "on_the_record": None,
    })
    return response.created_response(db.serialize(record))


@bp.get("/subject-response-requests/<subject_request_id>")
def get_subject_request(subject_request_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_subject(subject_request_id)))


@bp.get("/subject-response-requests")
def list_subject_requests():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("subject_response_requests"),
                           ["investigation_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/subject-response-requests/<subject_request_id>/attempts")
def document_attempt(subject_request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    record = db.get_subject(subject_request_id)
    payload = v.body()
    channel = v.field_enum(payload, "channel", CONTACT_CHANNELS)
    deliverable = v.field_bool(payload, "deliverable")
    note = v.field_string(payload, "note", min_len=1, max_len=300, non_blank=True)
    contact_detail = v.field_string(payload, "contact_detail", min_len=1, max_len=300,
                                    non_blank=False, optional=True, default=None,
                                    nullable=True)
    # Rung 10
    if record["status"] in ATTEMPT_FORBIDDEN_STATUSES:
        raise _invalid_subject_state(record)
    now = clock.now()
    was = record["status"]
    record["documented_attempts"] = list(record["documented_attempts"]) + [{
        "channel": channel,
        "contact_detail": contact_detail,
        "deliverable": deliverable,
        "note": note,
        "attempted_at": clock.iso(now),
    }]
    record["attempt_count"] = record["attempt_count"] + 1
    if was == "NOTICE_ELIGIBLE":
        # The first attempt starts the notice clock, and only the first one.
        record["status"] = "NOTICE_SENT"
        record["notice_sent_at"] = clock.iso(now)
        record["response_deadline_at"] = clock.iso(now + timedelta(hours=MIN_NOTICE_HOURS))
    elif was == "NOTICE_SENT":
        if not deliverable and record["attempt_count"] >= MIN_DOCUMENTED_ATTEMPTS:
            record["status"] = "UNREACHABLE"
    db.touch(record)
    return response.object_response(db.serialize(record))


@bp.post("/subject-response-requests/<subject_request_id>/response")
def record_response(subject_request_id):
    authenticate([ROLE_RECORDS_COORDINATOR])
    record = db.get_subject(subject_request_id)
    payload = v.body()
    response_text = v.field_text(payload, "response_text")
    on_the_record = v.field_bool(payload, "on_the_record")
    if record["status"] not in RESPONDABLE_STATUSES:
        raise _invalid_subject_state(record)
    record["status"] = "RESPONDED"
    record["response_text"] = response_text
    record["on_the_record"] = on_the_record
    db.touch(record)
    return response.object_response(db.serialize(record))
