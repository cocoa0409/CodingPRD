"""Course sessions, the attendance ledger, delivery and its compensating reversal."""
from datetime import timedelta

from flask import Blueprint, g

import calc
import ops
import serial
from core import ZERO2, base_row, d2, fail, now, store, touch
from routes.common import (
    body_fk,
    check_recruit_in_academy,
    check_recruit_not_terminal,
    created,
    listing,
    ok,
    path_row,
    require_roles,
)
from validate import (
    body,
    check_instant_interval,
    opt_int,
    query_enum,
    query_str,
    req_decimal,
    req_enum,
    req_instant,
    req_str,
)

bp = Blueprint("sessions", __name__)

SESSION_STATUSES = ("SCHEDULED", "UNDER_MIN_ENROLLMENT", "DELIVERED", "CANCELLED", "VOIDED")
LIVE_SESSION_STATUSES = ("SCHEDULED", "UNDER_MIN_ENROLLMENT", "DELIVERED")
ATTENDANCE_STATUSES = ("PRESENT", "PARTIAL", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")
LEDGER_STATUSES = ("PROVISIONAL", "CREDITED", "VOIDED")
SESSION_READ_ROLES = ("AcademyDirector", "TrainingCoordinator", "RecordsCustodian",
                      "AcademyInstructor")
TURNAROUND = timedelta(minutes=15)


def _check_instructor_authorized(instructor, topic_code):
    """Rung 50."""
    if (instructor is None
            or instructor["certification_status"] != "CERTIFIED"
            or topic_code not in instructor["authorized_topic_codes"]):
        fail("ERR_INSTRUCTOR_NOT_AUTHORIZED",
             "the instructor of record is not certified for this topic")


def _check_instructor_not_expired(instructor):
    """Rung 51."""
    expires_at = instructor.get("certification_expires_at")
    if expires_at is None or expires_at <= now():
        fail("ERR_INSTRUCTOR_CERT_EXPIRED",
             "the instructor's certification has lapsed")


def _check_plan_approved(plan, pinned=None):
    """Rung 52."""
    if plan is None or plan["status"] != "APPROVED":
        fail("ERR_LESSON_PLAN_NOT_APPROVED", "the lesson plan is not approved")
    if pinned is not None and pinned != plan["approved_revision_number"]:
        fail("ERR_LESSON_PLAN_NOT_APPROVED",
             "the pinned lesson plan revision has been superseded")


def _check_schedule_conflict(instructor_id, starts_at, ends_at, room_code):
    """Rung 62: half-open intersection plus the room-turnaround rule of §2.11."""
    for other in store.sessions.values():
        if other["instructor_id"] != instructor_id:
            continue
        if other["status"] not in LIVE_SESSION_STATUSES:
            continue
        if starts_at < other["ends_at"] and other["starts_at"] < ends_at:
            fail("ERR_INSTRUCTOR_SCHEDULE_CONFLICT",
                 "the instructor already teaches an overlapping session")
        if other["room_code"] == room_code:
            continue
        if starts_at >= other["ends_at"]:
            gap = starts_at - other["ends_at"]
        else:
            gap = other["starts_at"] - ends_at
        if gap < TURNAROUND:
            fail("ERR_INSTRUCTOR_SCHEDULE_CONFLICT",
                 "the instructor cannot change rooms within fifteen minutes")


def _check_topic_in_standard(cls, topic_code):
    """Rung 70."""
    standard = calc.standard_for_class(cls)
    if standard is None or calc.topic_requirement(standard, topic_code) is None:
        fail("ERR_TOPIC_NOT_IN_STANDARD",
             "topic %s is not part of the cohort's certification standard" % topic_code)


@bp.post("/course-sessions")
def create_session():
    require_roles("TrainingCoordinator")
    payload = body()
    cls = body_fk(payload, "academy_class_id", "classes")
    plan = body_fk(payload, "lesson_plan_id", "plans")
    instructor = body_fk(payload, "instructor_id", "instructors")

    academy_class_id = req_str(payload, "academy_class_id", min_len=1)
    lesson_plan_id = req_str(payload, "lesson_plan_id", min_len=1)
    instructor_id = req_str(payload, "instructor_id", min_len=1)
    room_code = req_str(payload, "room_code", min_len=1, max_len=16, upper=True)
    starts_at = req_instant(payload, "starts_at")
    ends_at = req_instant(payload, "ends_at")
    min_enrollment = opt_int(payload, "min_enrollment", minimum=0, default=3)

    check_instant_interval(starts_at, ends_at)

    topic_code = plan["topic_code"]
    _check_instructor_authorized(instructor, topic_code)
    _check_instructor_not_expired(instructor)
    _check_plan_approved(plan)
    _check_schedule_conflict(instructor_id, starts_at, ends_at, room_code)
    _check_topic_in_standard(cls, topic_code)

    row = base_row()
    row.update({
        "academy_class_id": academy_class_id,
        "lesson_plan_id": lesson_plan_id,
        "instructor_id": instructor_id,
        "room_code": room_code,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "min_enrollment": min_enrollment,
        "scheduled_hours": calc.session_scheduled_hours(starts_at, ends_at),
        "topic_code": topic_code,
        "pinned_lesson_plan_revision": plan["approved_revision_number"],
        "status": "SCHEDULED",
        "void_reason": None,
        "delivered_at": None,
    })
    store.sessions[row["id"]] = row
    ops.rederive_class_projection(cls)
    return created(serial.session_json(row))


@bp.get("/course-sessions/<course_session_id>")
def read_session(course_session_id):
    require_roles(*SESSION_READ_ROLES)
    row = path_row("sessions", course_session_id)
    return ok(serial.session_json(row))


@bp.get("/course-sessions")
def list_sessions():
    require_roles(*SESSION_READ_ROLES)
    academy_class_id = query_str("academy_class_id")
    lesson_plan_id = query_str("lesson_plan_id")
    instructor_id = query_str("instructor_id")
    topic_code = query_str("topic_code")
    status = query_enum("status", SESSION_STATUSES)

    def predicate(row):
        if academy_class_id is not None and row["academy_class_id"] != academy_class_id:
            return False
        if lesson_plan_id is not None and row["lesson_plan_id"] != lesson_plan_id:
            return False
        if instructor_id is not None and row["instructor_id"] != instructor_id:
            return False
        if topic_code is not None and row["topic_code"] != topic_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return listing("sessions", serial.session_json, predicate)


def _check_present_hours(status, present_hours, scheduled_hours):
    """Rung 68."""
    if status == "PRESENT":
        okay = present_hours == scheduled_hours
    elif status == "PARTIAL":
        okay = ZERO2 < present_hours < scheduled_hours
    else:
        okay = present_hours == ZERO2
    if not okay:
        fail("ERR_PRESENT_HOURS_INCONSISTENT",
             "present_hours is inconsistent with attendance status %s" % status)


@bp.post("/course-sessions/<course_session_id>/attendance")
def record_attendance(course_session_id):
    require_roles("AcademyInstructor", "TrainingCoordinator")
    session = path_row("sessions", course_session_id)
    payload = body()
    recruit = body_fk(payload, "recruit_id", "recruits")
    recruit_id = req_str(payload, "recruit_id", min_len=1)
    status = req_enum(payload, "status", ATTENDANCE_STATUSES)
    present_hours = req_decimal(payload, "present_hours")

    check_recruit_not_terminal(recruit)
    check_recruit_in_academy(recruit)

    for existing in store.attendance.values():
        if (existing["course_session_id"] == session["id"]
                and existing["recruit_id"] == recruit_id):
            fail("ERR_ATTENDANCE_ALREADY_RECORDED",
                 "attendance for this recruit is already recorded on this session")

    _check_present_hours(status, present_hours, d2(session["scheduled_hours"]))

    row = base_row()
    row.update({
        "course_session_id": session["id"],
        "recruit_id": recruit_id,
        "status": status,
        "present_hours": present_hours,
        "ledger_status": "PROVISIONAL",
        "credited_hours": ZERO2,
        "counted_absence_hours": ZERO2,
        "void_reason": None,
    })
    store.attendance[row["id"]] = row
    ops.rederive_enrollment(session, "up")
    return created(serial.attendance_json(row))


@bp.get("/attendance-records/<attendance_record_id>")
def read_attendance(attendance_record_id):
    require_roles(*SESSION_READ_ROLES)
    row = path_row("attendance", attendance_record_id)
    return ok(serial.attendance_json(row))


@bp.get("/attendance-records")
def list_attendance():
    require_roles(*SESSION_READ_ROLES)
    course_session_id = query_str("course_session_id")
    recruit_id = query_str("recruit_id")
    ledger_status = query_enum("ledger_status", LEDGER_STATUSES)

    def predicate(row):
        if course_session_id is not None and row["course_session_id"] != course_session_id:
            return False
        if recruit_id is not None and row["recruit_id"] != recruit_id:
            return False
        if ledger_status is not None and row["ledger_status"] != ledger_status:
            return False
        return True

    return listing("attendance", serial.attendance_json, predicate)


@bp.post("/course-sessions/<course_session_id>/deliver")
def deliver(course_session_id):
    require_roles("AcademyInstructor", "TrainingCoordinator")
    session = path_row("sessions", course_session_id)

    if session["status"] not in ("SCHEDULED", "UNDER_MIN_ENROLLMENT"):
        fail("ERR_SESSION_NOT_DELIVERABLE",
             "a session at %s cannot be closed out" % session["status"])
    if session["ends_at"] > now():
        fail("ERR_SESSION_NOT_DELIVERABLE",
             "the session has not finished yet")

    instructor = store.instructors.get(session["instructor_id"])
    _check_instructor_authorized(instructor, session["topic_code"])
    _check_instructor_not_expired(instructor)
    plan = store.plans.get(session["lesson_plan_id"])
    _check_plan_approved(plan, session["pinned_lesson_plan_revision"])

    ops.deliver_session(session)
    return ok(serial.session_json(session))


@bp.post("/course-sessions/<course_session_id>/void-delivery")
def void_delivery(course_session_id):
    require_roles("AcademyDirector")
    session = path_row("sessions", course_session_id)
    payload = body()
    reason = req_str(payload, "reason", min_len=1, max_len=2000)

    if session["status"] != "DELIVERED":
        fail("ERR_SESSION_NOT_VOIDABLE",
             "a session at %s cannot be voided" % session["status"])

    ops.void_session_delivery(session, reason)
    return ok(serial.session_json(session))
