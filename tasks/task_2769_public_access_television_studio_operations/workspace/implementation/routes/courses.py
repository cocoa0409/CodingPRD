"""The certification curriculum: courses and enrollments (PRD 3.1)."""

from flask import Blueprint

import constants as C
import db
import middleware
import serialize
import support
import validation
from errors import ApiError, bad_request, invalid_transition, not_found

bp = Blueprint("courses", __name__)

COURSE_READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_TRAINING_COORDINATOR, C.ROLE_PRODUCER)
ENROLLMENT_READ_ROLES = (C.ROLE_CENTER_ADMIN, C.ROLE_TRAINING_COORDINATOR, C.ROLE_PRODUCER)

PREREQUISITE_TIER = {"ADVANCED": "BASIC", "LIVE": "ADVANCED"}


# --------------------------------------------------------------------------- #
# training courses
# --------------------------------------------------------------------------- #
@bp.post("/training-courses")
def create_course():
    middleware.authorize(C.ROLE_TRAINING_COORDINATOR)
    body = validation.body()
    course_code = validation.req_string(body, "course_code")
    title = validation.req_string(body, "title")
    tier = validation.req_enum(body, "tier", C.COURSE_TIERS)
    grants = validation.req_enum_list(
        body, "grants_competency_codes", C.COMPETENCY_CODES, allow_empty=False
    )
    seat_capacity = validation.req_int(body, "seat_capacity", minimum=1)
    session_start_at = validation.req_datetime(body, "session_start_at")
    session_end_at = validation.req_datetime(body, "session_end_at")
    if session_end_at <= session_start_at:
        raise bad_request("session_end_at must be strictly after session_start_at")
    for row in db.all_rows("training_courses"):
        if row["course_code"] == course_code:
            raise ApiError("ERR_DUPLICATE_NATURAL_KEY", "This course_code is already published")
    row = db.new_row(
        "training_courses",
        {
            "course_code": course_code,
            "title": title,
            "tier": tier,
            "grants_competency_codes": grants,
            "seat_capacity": seat_capacity,
            "session_start_at": session_start_at,
            "session_end_at": session_end_at,
        },
    )
    return support.created("training_courses", row)


@bp.get("/training-courses/<course_id>")
def read_course(course_id):
    middleware.authorize(*COURSE_READ_ROLES)
    row = support.must_exist("training_courses", course_id)
    return support.single("training_courses", row)


@bp.get("/training-courses")
def list_courses():
    middleware.authorize(*COURSE_READ_ROLES)
    tier = validation.query_enum("tier", C.COURSE_TIERS)
    validation.pagination()
    rows = support.filter_rows("training_courses", [("tier", tier)])
    return support.collection_response("training_courses", rows)


# --------------------------------------------------------------------------- #
# enrollments
# --------------------------------------------------------------------------- #
@bp.post("/course-enrollments")
def create_enrollment():
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_TRAINING_COORDINATOR)
    body = validation.body()
    producer_id = validation.req_id(body, "producer_id")
    course_id = validation.req_id(body, "course_id")
    # priority 5: body foreign keys resolve in the order the fields are listed
    producer = db.get("producers", producer_id)
    if producer is None:
        raise not_found("producer", producer_id)
    course = db.get("training_courses", course_id)
    if course is None:
        raise not_found("training_course", course_id)
    middleware.require_owner(producer_id, user_id, role)
    # priority 10
    if producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", "The owning producer is not active")
    # priority 17
    prerequisite = PREREQUISITE_TIER.get(course["tier"])
    if prerequisite is not None and not _holds_passed_tier(producer_id, prerequisite):
        raise ApiError(
            "ERR_PREREQUISITE_NOT_MET",
            "A passed %s course is required before a %s course" % (prerequisite, course["tier"]),
        )
    # priority 18
    enrolled_count, _ = serialize.course_counts(course_id)
    if enrolled_count >= course["seat_capacity"]:
        raise ApiError("ERR_COURSE_FULL", "No seat remains on this course")
    # priority 37
    for row in db.all_rows("course_enrollments"):
        if row["producer_id"] != producer_id or row["course_id"] != course_id:
            continue
        if row["status"] in ("ENROLLED", "ATTENDED", "PASSED"):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", "This producer already holds a live enrollment")
    row = db.new_row(
        "course_enrollments",
        {
            "producer_id": producer_id,
            "course_id": course_id,
            "status": "ENROLLED",
            "practical_score": None,
            "attended_at": None,
            "graded_at": None,
        },
    )
    return support.created("course_enrollments", row)


def _holds_passed_tier(producer_id, tier):
    for row in db.all_rows("course_enrollments"):
        if row["producer_id"] != producer_id or row["status"] != "PASSED":
            continue
        course = db.get("training_courses", row["course_id"])
        if course is not None and course["tier"] == tier:
            return True
    return False


@bp.get("/course-enrollments/<enrollment_id>")
def read_enrollment(enrollment_id):
    middleware.authorize(*ENROLLMENT_READ_ROLES)
    row = support.must_exist("course_enrollments", enrollment_id)
    return support.single("course_enrollments", row)


@bp.get("/course-enrollments")
def list_enrollments():
    middleware.authorize(*ENROLLMENT_READ_ROLES)
    producer_id = validation.query_string("producer_id")
    course_id = validation.query_string("course_id")
    status = validation.query_enum("status", C.ENROLLMENT_STATUSES)
    validation.pagination()
    rows = support.filter_rows(
        "course_enrollments",
        [("producer_id", producer_id), ("course_id", course_id), ("status", status)],
    )
    return support.collection_response("course_enrollments", rows)


@bp.post("/course-enrollments/<enrollment_id>/attendance")
def record_attendance(enrollment_id):
    middleware.authorize(C.ROLE_TRAINING_COORDINATOR)
    body = validation.body()
    attended = validation.req_bool(body, "attended")
    row = support.must_exist("course_enrollments", enrollment_id)
    if row["status"] != "ENROLLED":
        raise invalid_transition("Attendance may only be recorded on an enrolled seat")
    course = db.get("training_courses", row["course_id"])
    # priority 23
    if db.now() < course["session_end_at"]:
        raise ApiError("ERR_COURSE_SESSION_NOT_ENDED", "The course session has not ended yet")
    if attended:
        row["status"] = "ATTENDED"
        row["attended_at"] = db.now()
    else:
        row["status"] = "FAILED"
    db.bump(row)
    return support.single("course_enrollments", row)


@bp.post("/course-enrollments/<enrollment_id>/grade")
def grade_enrollment(enrollment_id):
    middleware.authorize(C.ROLE_TRAINING_COORDINATOR)
    body = validation.body()
    practical_score = validation.req_int(body, "practical_score", minimum=0, maximum=100)
    row = support.must_exist("course_enrollments", enrollment_id)
    if row["status"] != "ATTENDED":
        raise invalid_transition("Only an attended enrollment may be graded")
    row["practical_score"] = practical_score
    row["graded_at"] = db.now()
    if practical_score >= C.PASS_SCORE_MIN:
        row["status"] = "PASSED"
        db.bump(row)
        producer = db.get("producers", row["producer_id"])
        if producer is not None:
            # competency_codes and certification_level are derived; the row is
            # still mutated, so its version advances (PRD 3.1).
            db.bump(producer)
    else:
        row["status"] = "FAILED"
        db.bump(row)
    return support.single("course_enrollments", row)


@bp.post("/course-enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    user_id, role = middleware.authorize(C.ROLE_PRODUCER, C.ROLE_TRAINING_COORDINATOR)
    validation.body()
    row = support.must_exist("course_enrollments", enrollment_id)
    middleware.require_owner(row["producer_id"], user_id, role)
    if row["status"] != "ENROLLED":
        raise invalid_transition("Only an enrolled seat may be withdrawn")
    course = db.get("training_courses", row["course_id"])
    # priority 24
    if db.now() >= course["session_start_at"]:
        raise ApiError("ERR_WITHDRAWAL_WINDOW_CLOSED", "The withdrawal window has closed")
    row["status"] = "WITHDRAWN"
    db.bump(row)
    return support.single("course_enrollments", row)
