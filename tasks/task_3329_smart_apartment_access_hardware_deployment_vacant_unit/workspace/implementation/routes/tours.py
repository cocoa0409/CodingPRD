"""Self-guided tours: request, identity verification, tour credential (PRD 3.6)."""

from flask import request

from calculations import IDENTITY_VERIFICATION_TTL_MINUTES, MAX_VERIFY_ATTEMPTS
from db import add_minutes, clock, db, iso, parse_instant, touch
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_IDENTITY_VERIFICATION_EXPIRED,
    ERR_INVALID_STATE,
    ApiError,
)
from middleware import require_roles
from records import body, require_value, serialize, validate_body
from response import paged, success
from svc_common import get_tour_session, get_unit, issue_credential, new_record

VERIFIABLE_STATES = ("REQUESTED", "DENIED", "VERIFIED")


@require_roles("PropertyManager", "LeasingAgent")
def create_tour_session(caller, unitId):
    payload = body()
    validate_body(
        payload,
        required=("prospect_name", "prospect_id_document", "requested_start_at"),
        optional=("duration_minutes",),
    )
    unit = get_unit(unitId)
    requested_start = parse_instant(
        require_value(payload, "requested_start_at"), "requested_start_at"
    )
    duration = payload.get("duration_minutes")
    if duration is None:
        duration = 60
    record = new_record(
        {
            "unit_id": unit["id"],
            "prospect_name": require_value(payload, "prospect_name"),
            "prospect_id_document": require_value(payload, "prospect_id_document"),
            "status": "REQUESTED",
            "requested_start_at": iso(requested_start),
            "duration_minutes": duration,
            "identity_verified_at": None,
            "verify_attempts": 0,
            "_credential_id": None,
        }
    )
    db.tour_sessions[record["id"]] = record
    return success(serialize(record), "object", 201)


@require_roles("LeasingAgent")
def verify_tour_session(caller, tourSessionId):
    payload = body()
    validate_body(payload, required=("identity_document_number",))
    supplied = require_value(payload, "identity_document_number")
    session = get_tour_session(tourSessionId)

    status = session.get("status")
    if status == "COMPLETED":
        raise ApiError(
            ERR_ALREADY_TERMINAL, "Tour session %s is COMPLETED" % tourSessionId
        )
    if status not in VERIFIABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Tour session %s cannot be verified from status %s"
            % (tourSessionId, status),
        )

    requested_start = parse_instant(session.get("requested_start_at"), "requested_start_at")
    window_end = add_minutes(requested_start, IDENTITY_VERIFICATION_TTL_MINUTES)
    if clock.now > window_end:
        raise ApiError(
            ERR_IDENTITY_VERIFICATION_EXPIRED,
            "The identity verification window for this tour session has elapsed",
        )

    if status == "DENIED" and session.get("verify_attempts", 0) >= MAX_VERIFY_ATTEMPTS:
        raise ApiError(
            ERR_INVALID_STATE,
            "Tour session %s has exhausted its verification attempts" % tourSessionId,
        )

    matches = supplied == session.get("prospect_id_document")

    if status == "REQUESTED":
        if matches:
            _verify_success(session)
        else:
            session["status"] = "DENIED"
            session["verify_attempts"] = session.get("verify_attempts", 0) + 1
            touch(session)
        return success(serialize(session), "object", 200)

    if status == "DENIED":
        if matches:
            _verify_success(session)
        else:
            session["status"] = "DENIED"
            session["verify_attempts"] = session.get("verify_attempts", 0) + 1
            touch(session)
        return success(serialize(session), "object", 200)

    # status == VERIFIED: the late-failure branch is the only declared transition
    if not matches:
        session["status"] = "DENIED"
        session["verify_attempts"] = session.get("verify_attempts", 0) + 1
        touch(session)
        credential = db.access_credentials.get(session.get("_credential_id"))
        if credential is not None and credential.get("status") != "REVOKED":
            credential["status"] = "REVOKED"
            touch(credential)
    session["verify_attempts"] = session.get("verify_attempts", 0)
    return success(serialize(session), "object", 200)


def _verify_success(session):
    """REQUESTED (or a successful retry) -> VERIFIED, minting the TOUR credential."""
    unit = get_unit(session["unit_id"])
    if unit.get("occupancy_status") != "VACANT":
        raise ApiError(
            ERR_INVALID_STATE,
            "Tour verification requires a VACANT unit",
        )
    requested_start = parse_instant(session.get("requested_start_at"), "requested_start_at")
    duration = int(session.get("duration_minutes") or 60)
    credential = issue_credential(
        unit_id=unit["id"],
        subject_resident_id=None,
        credential_type="TOUR",
        status="ACTIVE",
        valid_from=iso(requested_start),
        valid_until=iso(add_minutes(requested_start, duration)),
    )
    session["_credential_id"] = credential["id"]
    session["status"] = "VERIFIED"
    session["identity_verified_at"] = iso(clock.now)
    session["verify_attempts"] = session.get("verify_attempts", 0) + 1
    touch(session)
    return session


@require_roles("PropertyManager", "LeasingAgent")
def list_tour_sessions(caller):
    rows = list(db.tour_sessions.values())
    unit_id = request.args.get("unit_id")
    if unit_id:
        rows = [row for row in rows if row.get("unit_id") == unit_id]
    window, pagination = paged(rows)
    return success([serialize(row) for row in window], "array", 200, pagination)


API_ROUTES = [
    ("POST", "/units/<unitId>/tour-sessions", create_tour_session),
    ("POST", "/tour-sessions/<tourSessionId>/verify", verify_tour_session),
    ("GET", "/tour-sessions", list_tour_sessions),
]