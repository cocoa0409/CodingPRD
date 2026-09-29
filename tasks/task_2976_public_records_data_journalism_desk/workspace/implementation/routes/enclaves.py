"""SecureEnclave and EnclaveSession endpoints (PRD section 3.9)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db
import response
import validation as v
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_DATA_REPORTER, ROLE_LEGAL_COUNSEL,
                        ROLE_MANAGING_EDITOR, authenticate)

bp = Blueprint("enclaves", __name__)

DEFAULT_SANITIZATION_BUFFER_MINUTES = 30
BOOKABLE_DATASET_STATUSES = ("CLEAN_LOCKED", "QUARANTINED")


@bp.post("/secure-enclaves")
def create_enclave():
    authenticate([ROLE_LEGAL_COUNSEL, ROLE_MANAGING_EDITOR])
    payload = v.body()
    name = v.field_string(payload, "name", min_len=1, max_len=80, non_blank=True)
    max_documents = v.field_int(payload, "max_documents", minimum=1, maximum=100)
    buffer_minutes = v.field_int(payload, "sanitization_buffer_minutes", minimum=0, maximum=240,
                                optional=True,
                                default=DEFAULT_SANITIZATION_BUFFER_MINUTES)
    if buffer_minutes is None:
        buffer_minutes = DEFAULT_SANITIZATION_BUFFER_MINUTES
    enclave = db.insert("secure_enclaves", {
        "name": name,
        "sanitization_buffer_minutes": buffer_minutes,
        "max_documents": max_documents,
        "booked_session_count": 0,
    })
    return response.created_response(db.serialize(enclave))


def _conflicts(candidate_start, candidate_end, enclave):
    """Pairwise buffered-occupancy exclusion against every BOOKED session."""
    buffer_delta = timedelta(minutes=enclave["sanitization_buffer_minutes"])
    for row in db.sessions_of_enclave(enclave["id"]):
        if row["status"] != "BOOKED":
            continue
        other_start = clock.instant_of(row["start_at"])
        other_end = clock.instant_of(row["end_at"])
        if other_start is None or other_end is None:
            continue
        if candidate_start < (other_end + buffer_delta) \
                and other_start < (candidate_end + buffer_delta):
            return True
    return False


@bp.post("/enclave-sessions")
def create_session():
    user_id, _ = authenticate([ROLE_LEGAL_COUNSEL, ROLE_DATA_REPORTER])
    payload = v.body()
    enclave_id = v.field_string(payload, "enclave_id", min_len=1, non_blank=True)
    dataset_id = v.field_string(payload, "dataset_id", min_len=1, non_blank=True)
    start_at = v.field_instant(payload, "start_at")
    end_at = v.field_instant(payload, "end_at")
    document_count = v.field_int(payload, "document_count", minimum=1, maximum=100)
    purpose = v.field_string(payload, "purpose", min_len=1, max_len=300, non_blank=True)
    v.require_end_after_start(start_at, end_at, "start_at", "end_at")
    # Rung 6 -- references in declared order
    enclave = db.get_enclave(enclave_id)
    dataset = db.get_dataset(dataset_id)
    # Rung 13 -- the owning desk must not be in LOCKDOWN
    desk = db.desk_of_dataset(dataset)
    if desk is not None and desk["security_posture"] == "LOCKDOWN":
        raise ApiError("ERR_DESK_LOCKDOWN",
                       "The owning desk is in LOCKDOWN; no session may be booked.")
    # Rung 27 -- buffered occupancy exclusion
    if _conflicts(start_at, end_at, enclave):
        raise ApiError("ERR_ENCLAVE_SESSION_OVERLAP",
                       "The requested span overlaps the buffered occupancy of a booked session.")
    # Rung 29 -- per-session document ceiling
    if document_count > enclave["max_documents"]:
        raise ApiError("ERR_ENCLAVE_DOCUMENT_LIMIT",
                       "The enclave admits at most %d documents per session."
                       % enclave["max_documents"])
    # Rung 30 -- only a locked or quarantined dataset has a reviewable document set
    if dataset["status"] not in BOOKABLE_DATASET_STATUSES:
        raise ApiError("ERR_INVALID_DATASET_STATE",
                       "A session is not declared against dataset status %s." % dataset["status"])
    session = db.insert("enclave_sessions", {
        "enclave_id": enclave_id,
        "dataset_id": dataset_id,
        "start_at": clock.iso(start_at),
        "end_at": clock.iso(end_at),
        "document_count": document_count,
        "purpose": purpose,
        "opened_by_user_id": user_id,
        "status": "BOOKED",
        "documents_returned_count": None,
        "cancellation_reason_code": None,
    })
    enclave["booked_session_count"] = enclave["booked_session_count"] + 1
    db.touch(enclave)
    return response.created_response(db.serialize(session))


@bp.get("/enclave-sessions/<session_id>")
def get_session(session_id):
    authenticate(ALL_ROLES)
    return response.object_response(db.serialize(db.get_session(session_id)))


@bp.get("/enclave-sessions")
def list_sessions():
    authenticate(ALL_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(db.ordered("enclave_sessions"),
                           ["enclave_id", "dataset_id", "status"])
    window = rows[offset:offset + limit]
    return response.array_response(db.serialize_all(window), limit, offset, len(rows))


@bp.post("/enclave-sessions/<session_id>/closure")
def close_session(session_id):
    authenticate([ROLE_LEGAL_COUNSEL, ROLE_DATA_REPORTER])
    session = db.get_session(session_id)
    payload = v.body()
    documents_returned_count = v.field_int(payload, "documents_returned_count", minimum=0)
    # Rung 5 -- every document must be accounted for; this is a schema-level rule
    if documents_returned_count != session["document_count"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "documents_returned_count must equal the session's document_count of %d."
            % session["document_count"],
        )
    # Rung 10
    if session["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_SESSION_STATE",
                       "Closure is only declared from session status BOOKED.")
    session["status"] = "CLOSED"
    session["documents_returned_count"] = documents_returned_count
    db.touch(session)
    enclave = db.find("secure_enclaves", session["enclave_id"])
    if enclave is not None:
        enclave["booked_session_count"] = enclave["booked_session_count"] - 1
        db.touch(enclave)
    return response.object_response(db.serialize(session))
