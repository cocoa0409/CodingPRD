"""Career coaching and member event routes."""

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_STATE, ApiError
from middleware import (
    as_enum,
    as_int,
    as_string,
    as_timestamp,
    auth,
    raw_body,
    reject_unknown,
    require_fields,
    require_owner,
)
from response import ok_object
from routes.common import fetch, fetch_member, guard_member_view, list_response, mk
from services import calc, recompute, serialize, workflows
from timeutil import parse_ts

BP = Blueprint("coaching", __name__)

SESSION_KINDS = ("CAREER_COACHING", "MEMBER_EVENT")
CREATE_ALLOWED = {
    "member_id",
    "coach_ref",
    "session_kind",
    "starts_at",
    "ends_at",
    "capacity_total",
}


@BP.route("/benefits/coaching-sessions", methods=["POST"])
def book_session():
    auth(("BenefitsAdmin",))
    payload = raw_body()
    reject_unknown(payload, CREATE_ALLOWED)
    require_fields(payload, ("member_id", "coach_ref", "session_kind", "starts_at", "ends_at"))
    member_id = as_string(payload, "member_id")
    fetch_member(member_id)
    coach_ref = as_string(payload, "coach_ref")
    session_kind = as_enum(payload, "session_kind", SESSION_KINDS)
    starts_at = as_timestamp(payload, "starts_at")
    ends_at = as_timestamp(payload, "ends_at")
    if parse_ts(starts_at) > parse_ts(ends_at):
        raise ApiError(ERR_INVALID_STATE)
    capacity_total = as_int(payload, "capacity_total", required=False, default=1)
    if capacity_total < 1:
        raise ApiError(ERR_INVALID_STATE)

    if session_kind == "CAREER_COACHING":
        workflows.validate_career_overlap(coach_ref, starts_at, ends_at)
    else:
        workflows.validate_event_capacity(coach_ref, starts_at, ends_at, capacity_total)

    session = mk(
        "sessions",
        member_id=member_id,
        coach_ref=coach_ref,
        session_kind=session_kind,
        starts_at=starts_at,
        ends_at=ends_at,
        status="SCHEDULED",
        capacity_total=capacity_total,
        seats_reserved=0,
    )
    workflows.refresh_seats(session)
    return ok_object(serialize.session(session)), 201


@BP.route("/benefits/coaching-sessions", methods=["GET"])
def list_sessions():
    auth(("PlatformAdmin", "BenefitsAdmin", "Member"))
    items = list(DB.sessions.values())
    filters = {
        "member_id": "member_id",
        "coach_ref": "coach_ref",
        "session_kind": "session_kind",
        "status": "status",
    }
    return list_response(items, serialize.session, filters)


@BP.route("/benefits/coaching-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    user_id, role = auth(("Member", "PlatformAdmin", "BenefitsAdmin"))
    session = fetch("sessions", session_id)
    guard_member_view(user_id, role, session["member_id"])
    return ok_object(serialize.session(session))


@BP.route("/benefits/coaching-sessions/<session_id>/confirm", methods=["POST"])
def confirm_session(session_id):
    user_id, role = auth(("Member",))
    del role
    session = fetch("sessions", session_id)
    require_owner(user_id, session["member_id"])
    if session["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE)

    session["status"] = "CONFIRMED"
    from db import touch

    touch(session, DB.clock())
    workflows.refresh_seats(session)
    return ok_object(serialize.session(session))


@BP.route("/benefits/coaching-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    auth(("PlatformAdmin",))
    session = fetch("sessions", session_id)
    if session["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE)
    starts = parse_ts(session.get("starts_at"))
    if starts is not None and DB.clock() < starts:
        raise ApiError(ERR_INVALID_STATE)
    session["status"] = "COMPLETED"
    from db import touch

    touch(session, DB.clock())
    workflows.complete_career_session(session)
    recompute.recompute_member(session["member_id"])
    return ok_object(serialize.session(session))


@BP.route("/benefits/coaching-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    user_id, role = auth(("Member",))
    del role
    session = fetch("sessions", session_id)
    require_owner(user_id, session["member_id"])
    if session["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE)
    session["status"] = "CANCELLED"
    from db import touch

    touch(session, DB.clock())
    workflows.refresh_seats(session)
    return ok_object(serialize.session(session))