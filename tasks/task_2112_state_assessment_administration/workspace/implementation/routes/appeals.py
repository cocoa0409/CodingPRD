"""Score appeals: the data appeal window and its decisions (PRD 3.9)."""

from flask import Blueprint, request

import serialize
from db import create, db, now, ordered, touch
from errors import api_error
from middleware import (
    ALL_ROLES,
    DISTRICT_COORDINATOR,
    SCHOOL_COORDINATOR,
    STATE_OFFICER,
    body_reference,
    endpoint,
    json_body,
    require_scope,
    resolve,
)
from response import object_response, paginate
from validators import enum_field, identifier_field, integer_field, optional_text, string_field

bp = Blueprint("appeals", __name__)

REASON_CODES = {
    "SCORING_ERROR",
    "ROSTER_ERROR",
    "ACCOMMODATION_NOT_PROVIDED",
    "IRREGULARITY_IMPACT",
}
DECISIONS = {"UPHELD", "DENIED"}


@bp.post("/score-appeals")
@endpoint(SCHOOL_COORDINATOR, DISTRICT_COORDINATOR)
def file_appeal(actor):
    # Check 4 — the filer must cover the school (or district) that seated the student.
    named_registration = body_reference("registration_id")
    scoped = db.registrations.get(named_registration) if named_registration else None
    if scoped is not None:
        session = db.sessions.get(scoped["session_id"])
        school = db.schools.get(session["school_id"]) if session else None
        if actor.role == SCHOOL_COORDINATOR:
            require_scope(session is not None and session["school_id"] == actor.user_id)
        else:
            require_scope(school is not None and school["district_id"] == actor.user_id)

    body = json_body()
    registration_id = identifier_field(body, "registration_id")
    reason_code = enum_field(body, "reason_code", REASON_CODES)
    narrative = string_field(body, "narrative", min_length=1, max_length=2000)

    registration = resolve(db.registrations, registration_id, "ERR_REGISTRATION_NOT_FOUND")

    # Check 8 — the registration's own score status.
    if registration["score_status"] != "RELEASED":
        raise api_error("ERR_SCORE_NOT_RELEASED")

    session = db.sessions.get(registration["session_id"])
    window = db.windows.get(session["window_id"]) if session else None
    # Check 9 — the governing window's phase.
    if window is None or window["status"] != "RELEASED":
        raise api_error("ERR_WINDOW_PHASE_INVALID")

    # Check 20 — the appeal window must still be open.
    closes_at = window["appeal_window_closes_at"]
    if closes_at is None or not now() < closes_at:
        raise api_error("ERR_APPEAL_WINDOW_CLOSED")

    appeal = create(
        db.appeals,
        {
            "registration_id": registration_id,
            "reason_code": reason_code,
            "narrative": narrative,
            "filed_by_role": actor.role,
            "filed_by_user_id": actor.user_id,
            "filed_at": now(),
            "status": "FILED",
            "corrected_raw_score": None,
            "decided_at": None,
        },
    )
    registration["score_status"] = "UNDER_APPEAL"
    touch(registration)
    return object_response(serialize.appeal(appeal), 201)


@bp.get("/score-appeals/<score_appeal_id>")
@endpoint(*ALL_ROLES)
def read_appeal(actor, score_appeal_id):
    appeal = resolve(db.appeals, score_appeal_id, "ERR_SCORE_APPEAL_NOT_FOUND")
    return object_response(serialize.appeal(appeal))


@bp.get("/score-appeals")
@endpoint(*ALL_ROLES)
def list_appeals(actor):
    registration_id = request.args.get("registration_id")
    status = request.args.get("status")
    items = [
        appeal
        for appeal in db.appeals.values()
        if (registration_id is None or appeal["registration_id"] == registration_id)
        and (status is None or appeal["status"] == status)
    ]
    return paginate(ordered(items), serialize.appeal)


@bp.post("/score-appeals/<score_appeal_id>/decisions")
@endpoint(STATE_OFFICER)
def decide_appeal(actor, score_appeal_id):
    appeal = resolve(db.appeals, score_appeal_id, "ERR_SCORE_APPEAL_NOT_FOUND")

    body = json_body()
    decision = enum_field(body, "decision", DECISIONS)
    corrected_raw_score = integer_field(
        body, "corrected_raw_score", required=False, minimum=0, maximum=100
    )
    optional_text(body, "note")
    if decision == "UPHELD" and corrected_raw_score is None:
        raise api_error("ERR_INVALID_REQUEST", "corrected_raw_score is required to uphold an appeal.")

    # Check 8 — a decided appeal may not be decided again.
    if appeal["status"] != "FILED":
        raise api_error("ERR_SCORE_NOT_RELEASED")

    registration = db.registrations.get(appeal["registration_id"])
    appeal["decided_at"] = now()
    if decision == "UPHELD":
        appeal["status"] = "UPHELD"
        appeal["corrected_raw_score"] = corrected_raw_score
        # A registration invalidated mid-appeal is terminal and stays put; the
        # appeal itself must still be decidable so the window can finalize.
        if registration is not None and registration["score_status"] == "UNDER_APPEAL":
            registration["raw_score"] = corrected_raw_score
            registration["score_status"] = "CORRECTED"
            touch(registration)
    else:
        appeal["status"] = "DENIED"
        if registration is not None and registration["score_status"] == "UNDER_APPEAL":
            registration["score_status"] = "RELEASED"
            touch(registration)
    touch(appeal)
    return object_response(serialize.appeal(appeal))
