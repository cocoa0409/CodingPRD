"""Meeting and role assignment endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import auth
import calc
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("meetings", __name__, url_prefix="/toastmasters")

ROLE_CODES = (
    "TOASTMASTER",
    "TABLE_TOPICS_MASTER",
    "SPEAKER",
    "EVALUATOR",
    "TIMER",
    "AH_COUNTER",
    "GRAMMARIAN",
    "GENERAL_EVALUATOR",
)


def _get_meeting(meeting_id):
    return db.get(db.MEETINGS, meeting_id)


def _get_assignment(assignment_id):
    return db.get(db.ASSIGNMENTS, assignment_id)


def _role_class(role_code):
    return "SPEECH" if role_code == "SPEAKER" else "FUNCTIONARY"


def _member_membership_at(member_id, club_id):
    for membership in db.MEMBERSHIPS.values():
        if membership["member_id"] == member_id and membership["club_id"] == club_id:
            return membership
    return None


@bp.get("/meetings")
def list_meetings():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    meetings = list(db.MEETINGS.values())
    for query_name in ("club_id", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            meetings = [m for m in meetings if m.get(query_name) == wanted]

    meetings.sort(key=lambda m: m["created_at"])
    window, total, _ = db.paginate(meetings, limit, offset)
    return array(serializers.render_all("meeting", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/meetings/<meeting_id>")
def get_meeting(meeting_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("meeting", _get_meeting(meeting_id)))


@bp.post("/meetings")
def create_meeting():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    club_id = db.require_str(body, "club_id")
    scheduled_at = db.parse_dt(db.require(body, "scheduled_at"), "scheduled_at")
    duration_minutes = db.optional_int(body, "duration_minutes", calc.DEFAULT_DURATION_MINUTES)
    if duration_minutes <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'duration_minutes' must be positive.")
    venue_name = db.require_str(body, "venue_name")
    theme = db.optional(body, "theme")
    expected_club_version = db.require_int(body, "expected_club_version")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))
    auth.require_officer_of_club(principal, club_id)

    # Priority 4: the referenced club exists.
    club = db.get(db.CLUBS, club_id)

    # Priority 5: optimistic concurrency against the parent club.
    if expected_club_version != club["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Priority 8: the meeting window, scoped to the club.
    for existing in db.MEETINGS.values():
        if existing["club_id"] != club_id:
            continue
        if existing["status"] not in ("SCHEDULED", "HELD"):
            continue
        if calc.meeting_overlaps(
            scheduled_at,
            duration_minutes,
            existing["scheduled_at"],
            existing["duration_minutes"],
        ):
            raise ApiError("ERR_MEETING_OVERLAP")

    meeting = db.create(
        db.MEETINGS,
        {
            "club_id": club_id,
            "scheduled_at": scheduled_at,
            "duration_minutes": duration_minutes,
            "venue_name": venue_name,
            "theme": theme,
            "status": "SCHEDULED",
            "attendance_count": 0,
            "quorum_met": False,
            "filled_role_slots": 0,
            "required_role_slots": calc.REQUIRED_ROLE_SLOTS,
            "held_at": None,
        },
    )
    db.touch(club)
    return ok(serializers.render("meeting", meeting), status=201)


@bp.post("/meetings/<meeting_id>/close")
def close_meeting(meeting_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    outcome = db.require_enum(body, "outcome", ("HELD", "CANCELLED"))
    attendance_count = db.optional_int(body, "attendance_count", 0)
    attendee_member_ids = db.optional(body, "attendee_member_ids", [])
    if attendee_member_ids is None:
        attendee_member_ids = []
    if not isinstance(attendee_member_ids, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'attendee_member_ids' must be an array.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    meeting = _get_meeting(meeting_id)
    auth.require_officer_of_club(principal, meeting["club_id"])

    # Priority 6: a close requires a SCHEDULED meeting.
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    club = db.get(db.CLUBS, meeting["club_id"])

    if outcome == "CANCELLED":
        meeting["status"] = "CANCELLED"
        for assignment in recompute.assignments_of_meeting(meeting["id"]):
            if assignment["status"] == "ASSIGNED":
                assignment["status"] = "RELEASED"
                db.touch(assignment)
        recompute.recompute_meeting(meeting)
        db.touch(meeting)
        return ok(serializers.render("meeting", meeting))

    # Priority 13: closing as HELD requires a quorum of five.
    if attendance_count < 5:
        raise ApiError("ERR_QUORUM_NOT_MET")

    now = db.utcnow()
    meeting["status"] = "HELD"
    meeting["attendance_count"] = attendance_count
    meeting["quorum_met"] = True
    meeting["held_at"] = now

    attendees = set(attendee_member_ids)
    for assignment in recompute.assignments_of_meeting(meeting["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        if assignment["member_id"] in attendees:
            assignment["status"] = "COMPLETED"
            assignment["credit_awarded"] = assignment["role_class"] == "SPEECH"
        else:
            assignment["status"] = "NO_SHOW"
            assignment["credit_awarded"] = False
        db.touch(assignment)
        for membership in recompute.memberships_of_club(meeting["club_id"]):
            if membership["member_id"] == assignment["member_id"]:
                recompute.recompute_membership(membership)
                break

    recompute.recompute_meeting(meeting)
    recompute.touch_club(club)
    db.touch(meeting)
    return ok(serializers.render("meeting", meeting))


@bp.get("/role-assignments")
def list_assignments():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    assignments = list(db.ASSIGNMENTS.values())
    for query_name in ("meeting_id", "member_id", "role_class"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            assignments = [a for a in assignments if a.get(query_name) == wanted]

    assignments.sort(key=lambda a: a["created_at"])
    window, total, _ = db.paginate(assignments, limit, offset)
    return array(serializers.render_all("role_assignment", window), limit=limit,
                 offset=offset, total_count=total)


@bp.get("/role-assignments/<assignment_id>")
def get_assignment(assignment_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("role_assignment", _get_assignment(assignment_id)))


@bp.post("/role-assignments")
def create_assignment():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    meeting_id = db.require_str(body, "meeting_id")
    member_id = db.require_str(body, "member_id")
    role_code = db.require_enum(body, "role_code", ROLE_CODES)
    expected_meeting_version = db.require_int(body, "expected_meeting_version")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    # Priority 4: references resolved left to right, then in body field order.
    meeting = db.get(db.MEETINGS, meeting_id)
    db.get(db.MEMBERS, member_id)
    auth.require_officer_of_club(principal, meeting["club_id"])

    # Priority 5: optimistic concurrency against the parent meeting.
    if expected_meeting_version != meeting["version"]:
        raise ApiError("ERR_STALE_VERSION")

    # Priority 7: one ASSIGNED assignment per meeting and member.
    for existing in recompute.assignments_of_meeting(meeting_id):
        if existing["member_id"] == member_id and existing["status"] == "ASSIGNED":
            raise ApiError("ERR_DUPLICATE_ASSIGNMENT")

    role_class = _role_class(role_code)

    # Priority 9: the rolling speech-role window, across every club.
    if role_class == "SPEECH":
        window_start = meeting["scheduled_at"] - timedelta(days=calc.WINDOW_DAYS)
        window_end = meeting["scheduled_at"] + timedelta(days=calc.WINDOW_DAYS)
        prior = 0
        for existing in db.ASSIGNMENTS.values():
            if existing["member_id"] != member_id:
                continue
            if existing["role_class"] != "SPEECH":
                continue
            if existing["status"] not in ("ASSIGNED", "COMPLETED", "NO_SHOW"):
                continue
            other = db.MEETINGS.get(existing["meeting_id"])
            if other is None:
                continue
            if window_start <= other["scheduled_at"] <= window_end:
                prior += 1
        if prior >= calc.MAX_SPEECH_ROLES:
            raise ApiError("ERR_ROLE_WINDOW_EXCEEDED")

    # Priority 14: the meeting never holds more than seven filled slots.
    filled = len(
        [
            a
            for a in recompute.assignments_of_meeting(meeting_id)
            if a["status"] in ("ASSIGNED", "COMPLETED", "NO_SHOW")
        ]
    )
    if filled >= calc.REQUIRED_ROLE_SLOTS:
        raise ApiError("ERR_ROLE_SLOTS_FULL")

    # Priority 18: the assigned member must hold an ACTIVE, paid membership.
    club = db.get(db.CLUBS, meeting["club_id"])
    membership = _member_membership_at(member_id, meeting["club_id"])
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    recompute.require_membership_paid_active(membership, club)

    assignment = db.create(
        db.ASSIGNMENTS,
        {
            "meeting_id": meeting_id,
            "member_id": member_id,
            "role_code": role_code,
            "role_class": role_class,
            "status": "ASSIGNED",
            "credit_awarded": False,
            "released_reason": None,
        },
    )
    recompute.recompute_meeting(meeting)
    db.touch(meeting)
    return ok(serializers.render("role_assignment", assignment), status=201)


@bp.post("/role-assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    released_reason = db.require_str(body, "released_reason")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    assignment = _get_assignment(assignment_id)
    meeting = db.get(db.MEETINGS, assignment["meeting_id"])
    auth.require_officer_of_club(principal, meeting["club_id"])

    # Priority 6: a release requires an ASSIGNED slot on a SCHEDULED meeting.
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE")
    if meeting["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    assignment["status"] = "RELEASED"
    assignment["released_reason"] = released_reason
    recompute.recompute_meeting(meeting)
    db.touch(meeting)
    db.touch(assignment)
    return ok(serializers.render("role_assignment", assignment))
