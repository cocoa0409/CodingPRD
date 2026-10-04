"""Board meetings: scheduling, voting, closing, adoption cascade (PRD 3.8).

POST /board-meetings                 BoardAdmin
GET  /board-meetings                 all roles
GET  /board-meetings/{id}            all roles
POST /board-meetings/{id}/votes      BoardMember
POST /board-meetings/{id}/close      BoardAdmin
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_roles
from constants import (
    QUORUM_MIN_DISTINCT_MEMBERS,
    ROLES,
    VOTE_POSITIONS,
)
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import meeting_public
from validate import get_body, opt_str, req_enum, req_int, req_list_of_str, req_str

bp = Blueprint("board_meetings", __name__)


@bp.route("/board-meetings", methods=["POST"])
def create_meeting():
    _user_id, role = get_context()
    require_roles(role, ("BoardAdmin",))
    body = get_body()
    investigation_id = req_str(body, "investigation_id")
    room_id = req_str(body, "room_id")
    window_start = req_str(body, "window_start_utc")
    start_dt = clock.parse_iso(window_start)
    if start_dt is None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "field 'window_start_utc' must be an ISO 8601 UTC timestamp",
        )
    window_end = req_str(body, "window_end_utc")
    end_dt = clock.parse_iso(window_end)
    if end_dt is None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "field 'window_end_utc' must be an ISO 8601 UTC timestamp",
        )
    sitting_member_ids = req_list_of_str(body, "sitting_member_ids")

    investigation = domain.get_investigation(investigation_id)

    # Domain constraint (pipeline stage 7): quorum of distinct members.
    if len(set(sitting_member_ids)) < QUORUM_MIN_DISTINCT_MEMBERS:
        raise api_error(
            "ERR_QUORUM_NOT_MET",
            "sitting_member_ids must contain at least %d distinct members"
            % QUORUM_MIN_DISTINCT_MEMBERS,
        )

    # Temporal windows (pipeline stage 8).
    now = clock.clock_dt()
    if now is None or start_dt <= now:
        raise api_error(
            "ERR_WINDOW_IN_PAST",
            "window_start_utc must lie strictly after the current logical "
            "clock",
        )
    if end_dt <= start_dt:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "window_end_utc must lie strictly after window_start_utc",
        )
    for other in db.store["board_meetings"].values():
        if other["room_id"] != room_id:
            continue
        domain.refresh_meeting(other)
        if other["status"] not in ("SCHEDULED", "IN_SESSION"):
            continue
        other_start, other_buffered_end = domain.meeting_buffer_window(other)
        if other_start is None or other_buffered_end is None:
            continue
        if domain.windows_overlap(
            start_dt, end_dt, other_start, other_buffered_end
        ):
            raise api_error(
                "ERR_ROOM_WINDOW_CONFLICT",
                "the requested window overlaps another meeting on room %s "
                "(including its 60-minute turnaround buffer)" % room_id,
            )

    # Segregation of duties (pipeline stage 9): the IIC may not sit.
    if investigation["iic_user_id"] in sitting_member_ids:
        raise api_error(
            "ERR_SOD_IIC_ON_BOARD",
            "the investigation's investigator-in-charge may not sit on its "
            "board meeting",
        )

    meeting = db.add(
        "board_meetings",
        {
            "investigation_id": investigation["id"],
            "room_id": room_id,
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "sitting_member_ids": list(sitting_member_ids),
            "status": "SCHEDULED",
            "member_votes": [],
            "adopt_count": 0,
            "reject_count": 0,
            "abstain_count": 0,
            "outcome": None,
        },
    )
    return ok_object(meeting_public(meeting), status=201)


@bp.route("/board-meetings", methods=["GET"])
def list_meetings():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("board_meetings")
    for meeting in items:
        domain.refresh_meeting(meeting)
    investigation_id = request.args.get("investigation_id")
    if investigation_id is not None:
        items = [
            m for m in items if m["investigation_id"] == investigation_id
        ]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([meeting_public(m) for m in page], limit, offset, total)


@bp.route("/board-meetings/<meeting_id>", methods=["GET"])
def get_meeting(meeting_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    meeting = domain.get_meeting(meeting_id)
    return ok_object(meeting_public(meeting), status=200)


@bp.route("/board-meetings/<meeting_id>/votes", methods=["POST"])
def cast_vote(meeting_id):
    user_id, role = get_context()
    require_roles(role, ("BoardMember",))
    meeting = domain.get_meeting(meeting_id)
    if user_id not in meeting["sitting_member_ids"]:
        raise api_error(
            "ERR_NOT_SITTING_MEMBER",
            "the caller is not a sitting member of this meeting",
        )
    body = get_body()
    position = req_enum(body, "position", VOTE_POSITIONS)
    expected_version = req_int(body, "expected_meeting_version")
    dissent_text = opt_str(body, "dissent_text")
    if dissent_text is not None and position != "REJECT":
        raise api_error(
            "ERR_INVALID_REQUEST",
            "dissent_text is permitted only with position REJECT",
        )

    domain.refresh_meeting(meeting)
    if meeting["status"] != "IN_SESSION":
        raise api_error(
            "ERR_MEETING_NOT_IN_SESSION",
            "votes require the meeting to be effectively IN_SESSION",
        )

    existing = None
    for vote in meeting["member_votes"]:
        if vote["member_user_id"] == user_id:
            existing = vote
            break

    if position == "RETRACT" and existing is None:
        raise api_error(
            "ERR_NO_VOTE_TO_RETRACT",
            "the caller has no vote on record to retract",
        )
    if expected_version != meeting["version"]:
        raise api_error(
            "ERR_STALE_VERSION",
            "expected_meeting_version does not match the meeting's current "
            "version",
        )

    if position == "RETRACT":
        meeting["member_votes"].remove(existing)
    elif existing is None:
        meeting["member_votes"].append(
            {
                "member_user_id": user_id,
                "position": position,
                "dissent_text": dissent_text if position == "REJECT" else None,
                "cast_at": clock.get_clock(),
            }
        )
    else:
        existing["position"] = position
        existing["dissent_text"] = (
            dissent_text if position == "REJECT" else None
        )
        existing["cast_at"] = clock.get_clock()

    domain.recompute_vote_tallies(meeting)
    db.touch(meeting)
    return ok_object(meeting_public(meeting), status=200)


@bp.route("/board-meetings/<meeting_id>/close", methods=["POST"])
def close_meeting(meeting_id):
    _user_id, role = get_context()
    require_roles(role, ("BoardAdmin",))
    meeting = domain.get_meeting(meeting_id)
    domain.refresh_meeting(meeting)

    if meeting["status"] != "IN_SESSION":
        raise api_error(
            "ERR_MEETING_NOT_IN_SESSION",
            "closing requires the meeting to be effectively IN_SESSION",
        )
    investigation = db.store["investigations"].get(meeting["investigation_id"])
    if investigation is None or investigation["phase"] != "BOARD_REVIEW":
        raise api_error(
            "ERR_INVESTIGATION_PHASE_INVALID",
            "a meeting can only close into an investigation in BOARD_REVIEW",
        )

    domain.recompute_vote_tallies(meeting)
    adopted = meeting["adopt_count"] > meeting["reject_count"]
    meeting["outcome"] = "ADOPTED" if adopted else "NOT_ADOPTED"
    meeting["status"] = "COMPLETED"

    if adopted:
        # Cascade link 2: Investigation BOARD_REVIEW -> ADOPTED with docket
        # FINAL and groups DISBANDED.
        investigation["phase"] = "ADOPTED"
        if investigation["docket_status"] == "OPEN":
            investigation["docket_status"] = "FINAL"
        for group in db.store["groups"].values():
            if group["investigation_id"] != investigation["id"]:
                continue
            if group["status"] in ("ACTIVE", "COMPLETE"):
                group["status"] = "DISBANDED"
                db.touch(group)
        # Cascade link 3: AccidentCase LAUNCHED -> CLOSED_ADOPTED.
        case = db.store["accident_cases"].get(investigation["accident_case_id"])
        if case is not None and case["status"] == "LAUNCHED":
            case["status"] = "CLOSED_ADOPTED"
            db.touch(case)
        db.touch(investigation)
    else:
        investigation["phase"] = "ANALYSIS"
        db.touch(investigation)

    db.touch(meeting)
    return ok_object(meeting_public(meeting), status=200)
