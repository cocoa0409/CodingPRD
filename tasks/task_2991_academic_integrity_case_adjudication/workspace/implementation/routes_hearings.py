"""Hearing rooms, sessions, quorum and panel votes (PRD 3.7)."""

from flask import Blueprint, request

import calc
import cascades
from db import S, new_immutable_row, new_row, touch
from errors import fail
from lookup import (case_or_404, faculty_or_404, filter_rows, room_or_404, session_or_404,
                    vote_or_404)
from middleware import (ROLE_APPEALS_DEAN, ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR,
                        ROLE_STUDENT, auth, require_owner)
from response import created, ok, ok_list, pagination
from serializers import room_json, session_json, vote_json
from shapes import Field, peek, validate
from util import add_days

bp = Blueprint("hearings", __name__)

ROOM_FIELDS = [
    Field("code", "string", pattern=r"^[A-Z0-9-]{2,12}$"),
    Field("seat_capacity", "integer", minimum=4, maximum=200),
    Field("buffer_minutes", "integer", required=False, default=30, minimum=0, maximum=120),
    Field("sessions_per_day_cap", "integer", required=False, default=2, minimum=1, maximum=8),
]

SESSION_FIELDS = [
    Field("case_id", "string"),
    Field("room_id", "string"),
    Field("chair_id", "string"),
    Field("panelist_ids", "string_array"),
    Field("start_at", "datetime"),
    Field("end_at", "datetime"),
]

CANCEL_FIELDS = [Field("cancel_reason", "string", min_len=1, max_len=500)]

ADJOURN_FIELDS = [Field("adjourn_reason", "string", min_len=1, max_len=500)]

VOTE_FIELDS = [
    Field("session_id", "string"),
    Field("panelist_id", "string"),
    Field("verdict", "enum", values=("RESPONSIBLE", "NOT_RESPONSIBLE", "ABSTAIN")),
    Field("severity_recommendation", "integer", required=False, minimum=1, maximum=8),
]

SCHEDULE_CASE_STATES = ("NOTIFIED", "FORMAL_REFERRED")


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


# ---------------------------------------------------------------- rooms

@bp.route("/integrity/hearing-rooms", methods=["POST"])
def create_room():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(ROOM_FIELDS)
    for existing in S.rooms.values():
        if existing["code"] == body["code"]:
            fail("ERR_DUPLICATE_RESOURCE", "A hearing room with this code already exists.")
    row = new_row(
        code=body["code"],
        seat_capacity=body["seat_capacity"],
        buffer_minutes=body["buffer_minutes"],
        sessions_per_day_cap=body["sessions_per_day_cap"],
    )
    S.rooms[row["id"]] = row
    return created(room_json(row))


@bp.route("/integrity/hearing-rooms", methods=["GET"])
def list_rooms():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR])
    limit, offset = pagination()
    rows = filter_rows(S.rooms, {"code": "code"})
    return ok_list(rows, room_json, limit, offset)


@bp.route("/integrity/hearing-rooms/<row_id>", methods=["GET"])
def read_room(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR])
    return ok(room_json(room_or_404(row_id)))


# ---------------------------------------------------------------- sessions

@bp.route("/integrity/hearing-sessions", methods=["POST"])
def schedule_session():
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(SESSION_FIELDS)
    case = case_or_404(body["case_id"])
    room = room_or_404(body["room_id"])
    chair = faculty_or_404(body["chair_id"])
    for panelist_id in body["panelist_ids"]:
        faculty_or_404(panelist_id)
    if case["adjudication_status"] not in SCHEDULE_CASE_STATES:
        fail("ERR_CASE_STATE_INVALID",
             "A hearing may only be scheduled while the case is in NOTIFIED or "
             "FORMAL_REFERRED.")
    if case["pathway"] != "FORMAL":
        fail("ERR_CASE_PATHWAY_NOT_SET", "The case is not on the FORMAL pathway.")
    if calc.faculty_training_status(chair) != "CURRENT":
        fail("ERR_CHAIR_TRAINING_LAPSED", "The nominated chair's integrity training has lapsed.")
    conflicted = calc.conflicted_faculty_ids(case)
    if body["chair_id"] in conflicted:
        fail("ERR_PANEL_CONFLICT_OF_INTEREST",
             "The chair may not be the case's reporter or the offering's instructor.")
    for panelist_id in body["panelist_ids"]:
        if panelist_id in conflicted:
            fail("ERR_PANEL_CONFLICT_OF_INTEREST",
                 "No panelist may be the case's reporter or the offering's instructor.")
    notice = calc.governing_notice(case["id"])
    start_at = body["start_at"]
    end_at = body["end_at"]
    if notice is None or start_at < add_days(notice["sent_at"], calc.MIN_HEARING_NOTICE_DAYS):
        fail("ERR_NOTICE_PERIOD_TOO_SHORT",
             "The hearing must start at least 10 days after the governing notice.")
    if calc.room_buffer_conflict(room, start_at, end_at):
        fail("ERR_ROOM_BUFFER_CONFLICT",
             "The room's buffered interval collides with another session.")
    problem = calc.interval_problem(start_at, end_at)
    if problem is not None:
        fail("ERR_MEETING_WINDOW_INVALID", problem)
    required = calc.required_panel_size(case["recommended_ladder_rank"])
    panelists = body["panelist_ids"]
    if len(panelists) != required:
        fail("ERR_PANEL_SIZE_INVALID",
             "This case requires exactly %d panelists." % required)
    if len(set(panelists)) != len(panelists):
        fail("ERR_PANEL_SIZE_INVALID", "panelist_ids must not contain duplicates.")
    if body["chair_id"] in panelists:
        fail("ERR_PANEL_SIZE_INVALID", "panelist_ids must not contain the chair.")
    if calc.room_daily_session_count(room, start_at) >= room["sessions_per_day_cap"]:
        fail("ERR_ROOM_DAILY_CAPACITY_EXCEEDED",
             "The room already holds its daily maximum of sessions on that date.")
    row = new_row(
        case_id=case["id"],
        room_id=room["id"],
        chair_id=chair["id"],
        panelist_ids=list(panelists),
        required_panel_size=required,
        start_at=start_at,
        end_at=end_at,
        status="SCHEDULED",
        round_number=case["hearing_round"] + 1,
        quorum_required=calc.quorum_required(required),
        panel_finding=None,
        panel_severity_recommendation=None,
        adjourn_reason=None,
    )
    S.sessions[row["id"]] = row
    case["hearing_round"] = case["hearing_round"] + 1
    cascades.create_notice(case["id"], "HEARING_NOTICE")
    case["adjudication_status"] = "HEARING_SCHEDULED"
    touch(case)
    return created(session_json(row))


@bp.route("/integrity/hearing-sessions", methods=["GET"])
def list_sessions():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR, ROLE_STUDENT, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    fk_filter("room_id", room_or_404)
    fk_filter("chair_id", faculty_or_404)
    rows = filter_rows(S.sessions, {
        "case_id": "case_id",
        "room_id": "room_id",
        "chair_id": "chair_id",
        "status": "status",
    })
    return ok_list(rows, session_json, limit, offset)


@bp.route("/integrity/hearing-sessions/<row_id>", methods=["GET"])
def read_session(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR, ROLE_STUDENT, ROLE_APPEALS_DEAN])
    return ok(session_json(session_or_404(row_id)))


@bp.route("/integrity/hearing-sessions/<row_id>/convene", methods=["POST"])
def convene_session(row_id):
    actor = auth([ROLE_PANEL_CHAIR])
    known = S.sessions.get(row_id)
    if known is not None:
        require_owner(actor, known["chair_id"])
    session = session_or_404(row_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID", "Only a SCHEDULED session may be convened.")
    if S.clock < session["start_at"]:
        fail("ERR_MEETING_WINDOW_INVALID",
             "The logical clock has not reached the session's start_at.")
    if not calc.response_window_closed(session["case_id"]):
        fail("ERR_RESPONSE_WINDOW_OPEN", "The student's response window is still open.")
    if calc.advisor_request_pending(session["case_id"]):
        fail("ERR_ADVISOR_REQUEST_PENDING",
             "An advisor engagement of this case is still awaiting review.")
    session["status"] = "CONVENED"
    touch(session)
    case = S.cases.get(session["case_id"])
    if case is not None:
        case["adjudication_status"] = "HEARING_IN_PROGRESS"
        touch(case)
    return ok(session_json(session))


@bp.route("/integrity/hearing-sessions/<row_id>/adjourn", methods=["POST"])
def adjourn_session(row_id):
    actor = auth([ROLE_PANEL_CHAIR])
    known = S.sessions.get(row_id)
    if known is not None:
        require_owner(actor, known["chair_id"])
    body = validate(ADJOURN_FIELDS)
    session = session_or_404(row_id)
    if session["status"] != "CONVENED":
        fail("ERR_SESSION_STATE_INVALID", "Only a CONVENED session may be adjourned.")
    session["status"] = "ADJOURNED"
    session["adjourn_reason"] = body["adjourn_reason"]
    touch(session)
    # The room's booked minutes are NOT released: the room was truly occupied.
    cascades.create_notice(session["case_id"], "REHEARING_NOTICE")
    case = S.cases.get(session["case_id"])
    if case is not None:
        case["adjudication_status"] = "FORMAL_REFERRED"
        touch(case)
    return ok(session_json(session))


@bp.route("/integrity/hearing-sessions/<row_id>/decide", methods=["POST"])
def decide_session(row_id):
    actor = auth([ROLE_PANEL_CHAIR])
    known = S.sessions.get(row_id)
    if known is not None:
        require_owner(actor, known["chair_id"])
    session = session_or_404(row_id)
    if session["status"] != "CONVENED":
        fail("ERR_SESSION_STATE_INVALID", "Only a CONVENED session may be decided.")
    votes = calc.votes_of_session(session["id"])
    # Abstentions count toward quorum; the quorum check runs strictly first.
    if len(votes) < session["quorum_required"]:
        fail("ERR_QUORUM_NOT_MET", "Fewer votes were cast than the session's quorum requires.")
    effective, finding, recommendation = calc.panel_tally(session)
    if effective == 0:
        fail("ERR_NO_EFFECTIVE_VOTES", "Every vote cast was an abstention.")
    session["panel_finding"] = finding
    session["panel_severity_recommendation"] = recommendation
    session["status"] = "DECIDED"
    touch(session)
    case = S.cases.get(session["case_id"])
    if case is not None:
        case["responsibility_finding"] = finding
        case["finding_basis"] = "PANEL"
        case["panel_severity_recommendation"] = recommendation
        # The panel recommendation now acts as a floor under the formal algorithm.
        calc.apply_assessment(case)
        case["decided_at"] = S.clock
        if finding == "RESPONSIBLE":
            case["adjudication_status"] = "DECIDED"
        else:
            case["adjudication_status"] = "DISMISSED"
            case["dismiss_reason"] = "NOT_RESPONSIBLE_PANEL_FINDING"
        touch(case)
        cascades.recompute_department_of_case(case)
    return ok(session_json(session))


@bp.route("/integrity/hearing-sessions/<row_id>/cancel", methods=["POST"])
def cancel_session(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(CANCEL_FIELDS)
    session = session_or_404(row_id)
    if session["status"] != "SCHEDULED":
        fail("ERR_SESSION_STATE_INVALID", "Only a SCHEDULED session may be cancelled.")
    session["status"] = "CANCELLED"
    session["cancel_reason"] = body["cancel_reason"]
    touch(session)
    # The room ledger is derived, so cancelling releases exactly what scheduling
    # reserved. hearing_round is deliberately NOT decremented (PRD 3.7).
    case = S.cases.get(session["case_id"])
    if case is not None:
        case["adjudication_status"] = "FORMAL_REFERRED"
        touch(case)
    return ok(session_json(session))


# ---------------------------------------------------------------- votes

@bp.route("/integrity/panel-votes", methods=["POST"])
def cast_vote():
    actor = auth([ROLE_PANEL_CHAIR])
    hinted = peek("session_id")
    known = S.sessions.get(hinted) if isinstance(hinted, str) else None
    if known is not None:
        require_owner(actor, known["chair_id"])
    body = validate(VOTE_FIELDS)
    session = session_or_404(body["session_id"])
    faculty_or_404(body["panelist_id"])
    if session["status"] != "CONVENED":
        fail("ERR_SESSION_STATE_INVALID", "Votes may only be cast while the session is CONVENED.")
    case = S.cases.get(session["case_id"])
    conflicted = calc.conflicted_faculty_ids(case) if case is not None else set()
    if body["panelist_id"] in conflicted:
        fail("ERR_PANEL_CONFLICT_OF_INTEREST",
             "The case's reporter may never vote on the panel.")
    if body["panelist_id"] not in session["panelist_ids"]:
        fail("ERR_NOT_A_PANELIST", "panelist_id is not an element of the session's panel.")
    recommendation = body["severity_recommendation"]
    if body["verdict"] == "RESPONSIBLE" and recommendation is None:
        fail("ERR_SEVERITY_RECOMMENDATION_REQUIRED",
             "severity_recommendation is required on a RESPONSIBLE verdict.")
    if body["verdict"] != "RESPONSIBLE" and recommendation is not None:
        fail("ERR_SEVERITY_RECOMMENDATION_NOT_ALLOWED",
             "severity_recommendation is not allowed on this verdict.")
    for vote in calc.votes_of_session(session["id"]):
        if vote["panelist_id"] == body["panelist_id"]:
            fail("ERR_DUPLICATE_VOTE", "This panelist has already voted in this session.")
    row = new_immutable_row(
        session_id=session["id"],
        panelist_id=body["panelist_id"],
        verdict=body["verdict"],
        severity_recommendation=recommendation,
        cast_at=S.clock,
    )
    S.votes[row["id"]] = row
    return created(vote_json(row))


@bp.route("/integrity/panel-votes", methods=["GET"])
def list_votes():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR, ROLE_APPEALS_DEAN])
    limit, offset = pagination()
    fk_filter("session_id", session_or_404)
    fk_filter("panelist_id", faculty_or_404)
    rows = filter_rows(S.votes, {
        "session_id": "session_id",
        "panelist_id": "panelist_id",
        "verdict": "verdict",
    })
    return ok_list(rows, vote_json, limit, offset)


@bp.route("/integrity/panel-votes/<row_id>", methods=["GET"])
def read_vote(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR, ROLE_APPEALS_DEAN])
    return ok(vote_json(vote_or_404(row_id)))
