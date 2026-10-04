"""Chapters, volunteer course sessions, and enrollment."""

from flask import Blueprint

from auth import forbidden, require_roles
from db import locked, mint, store, touch
from serializers import chapter_view, session_view
from services import instructor_conflict, member_in_good_standing, room_conflict
from util import (
    err,
    get_body,
    is_int,
    paginate,
    parse_datetime_lenient,
    require_str,
    success_object,
)

bp = Blueprint("chapters", __name__)

COURSE_KINDS = {"TAX_PREP", "DRIVER_SAFETY"}
CHAPTER_READ_ROLES = ("MemberServicesAgent", "ChapterCoordinator", "PlatformAdmin")
SESSION_READ_ROLES = ("ChapterCoordinator", "MemberServicesAgent", "Member", "PlatformAdmin")


@bp.post("/api/chapters")
@locked
def create_chapter():
    require_roles("MemberServicesAgent")
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    city = require_str(body, "city")
    chapter = mint(store.chapters)
    chapter.update({"name": name, "state_code": state_code, "city": city})
    return success_object(chapter_view(chapter), status=201)


@bp.get("/api/chapters/<chapter_id>")
@locked
def get_chapter(chapter_id):
    require_roles(*CHAPTER_READ_ROLES)
    chapter = store.chapters.get(chapter_id)
    if chapter is None:
        err("ERR_NOT_FOUND", 404, "Chapter not found")
    return success_object(chapter_view(chapter))


@bp.post("/api/chapters/<chapter_id>/course-sessions")
@locked
def create_course_session(chapter_id):
    user_id, _ = require_roles("ChapterCoordinator")
    # Rung 3: the coordinator acts only for their own chapter.
    if user_id != chapter_id:
        forbidden("ChapterCoordinator may only schedule sessions for their own chapter")
    body = get_body()
    # Rung 5: schema (including both timing faults).
    course_kind = body.get("course_kind")
    if course_kind is None or course_kind not in COURSE_KINDS:
        err("ERR_INVALID_REQUEST", 400, "course_kind must be TAX_PREP or DRIVER_SAFETY")
    instructor_name = require_str(body, "instructor_name")
    start_raw = body.get("start_time")
    end_raw = body.get("end_time")
    start = parse_datetime_lenient(start_raw)
    end = parse_datetime_lenient(end_raw)
    if start is None or end is None:
        err("ERR_INVALID_REQUEST", 400, "start_time and end_time are required ISO 8601 datetimes")
    if end <= start:
        err("ERR_INVALID_REQUEST", 400, "end_time must be strictly after start_time")
    if start <= store.clock_dt:
        err("ERR_INVALID_REQUEST", 400, "start_time must be in the future")
    capacity = body.get("capacity")
    if capacity is None or not is_int(capacity) or capacity < 1:
        err("ERR_INVALID_REQUEST", 400, "capacity must be an integer of at least 1")
    # Rung 6: existence.
    if chapter_id not in store.chapters:
        err("ERR_NOT_FOUND", 404, "Chapter not found")
    # Rung 11: room-buffer rule first, then the instructor half-open overlap.
    if room_conflict(chapter_id, start, end):
        err("ERR_SESSION_OVERLAP", 409, "Session conflicts with the chapter room's turnover buffer")
    if instructor_conflict(instructor_name, start, end):
        err("ERR_INSTRUCTOR_DOUBLE_BOOKED", 409, "Instructor has an overlapping session")
    session = mint(store.sessions)
    session.update(
        {
            "chapter_id": chapter_id,
            "course_kind": course_kind,
            "instructor_name": instructor_name,
            "start_time": start_raw,
            "end_time": end_raw,
            "capacity": capacity,
            "enrolled_member_ids": [],
        }
    )
    return success_object(session_view(session), status=201)


@bp.get("/api/chapters/<chapter_id>/course-sessions")
@locked
def list_course_sessions(chapter_id):
    require_roles(*SESSION_READ_ROLES)
    if chapter_id not in store.chapters:
        err("ERR_NOT_FOUND", 404, "Chapter not found")
    sessions = [
        s
        for s in sorted(store.sessions.values(), key=lambda r: r["_seq"])
        if s["chapter_id"] == chapter_id
    ]
    return paginate([session_view(s) for s in sessions])


@bp.post("/api/course-sessions/<session_id>/enroll")
@locked
def enroll_member(session_id):
    user_id, role = require_roles("Member", "ChapterCoordinator")
    body = get_body()
    member_id = body.get("member_id")
    # Rung 3: a Member self-enrolls; a ChapterCoordinator may enroll anyone.
    if role == "Member" and member_id is not None and member_id != user_id:
        forbidden("A Member may only enroll themselves")
    if member_id is None or not isinstance(member_id, str):
        err("ERR_INVALID_REQUEST", 400, "member_id is required")
    # Rung 6: path id first, then the body FK.
    session = store.sessions.get(session_id)
    if session is None:
        err("ERR_NOT_FOUND", 404, "Course session not found")
    member = store.members.get(member_id)
    if member is None:
        err("ERR_NOT_FOUND", 404, "Member not found")
    # Rung 8, timing first: still SCHEDULED and start strictly after the clock.
    start = parse_datetime_lenient(session["start_time"])
    end = parse_datetime_lenient(session["end_time"])
    if store.clock_dt >= end or start <= store.clock_dt:
        err("ERR_ENROLLMENT_CLOSED", 409, "Enrollment is closed for this session")
    # Rung 9, standing second.
    if not member_in_good_standing(member):
        err("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not in good standing")
    # Rung 11: uniqueness third, capacity last.
    if member_id in session["enrolled_member_ids"]:
        err("ERR_ALREADY_ENROLLED", 409, "Member is already enrolled in this session")
    if len(session["enrolled_member_ids"]) >= session["capacity"]:
        err("ERR_SESSION_FULL", 409, "Session capacity has been reached")
    session["enrolled_member_ids"].append(member_id)
    touch(session)
    return success_object(session_view(session))
