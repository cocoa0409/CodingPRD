"""Shifts (PRD 3.3): rostering, the travel-buffered collision rule and the vacate cascade."""

from flask import Blueprint

import auth
import db
import validation
from errors import fail
from routes import common
from services import calc, cascade

bp = Blueprint("staff", __name__)

STATION_ROLES = ("MARSHAL", "WATER_SAFETY")
COURSE_WIDE_ROLES = ("MEDIC", "SWEEP")


@bp.post("/ocr/courses/<course_id>/staff-assignments")
def roster_shift(course_id):
    auth.require(auth.SAFETY_OFFICER)
    course = validation.path_course(course_id)
    payload = validation.body()
    staff_person_id = validation.field_str(payload, "staff_person_id", 1, 40)
    staff_role = validation.field_enum(payload, "staff_role", validation.STAFF_ROLES)
    certification_level = validation.field_enum(
        payload, "certification_level", validation.CERTIFICATION_LEVELS
    )
    shift_start = validation.field_datetime(payload, "shift_start_utc")
    shift_end = validation.field_datetime(payload, "shift_end_utc")
    if shift_end <= shift_start:
        fail("ERR_INVALID_REQUEST", "Field 'shift_end_utc' must be after shift_start_utc.")
    if staff_role in COURSE_WIDE_ROLES:
        # Rung 4: a course-wide shift may not name a station at all.
        validation.forbid_field(
            payload,
            "obstacle_id",
            message="Field 'obstacle_id' must be omitted for a %s shift." % staff_role,
        )
    obstacle_id = validation.field_id(payload, "obstacle_id", default=None)

    # Rung 5: a named station must stand on the addressed course.
    obstacle = None
    if obstacle_id is not None:
        obstacle = validation.fk_obstacle(obstacle_id, course_id=course["id"])

    # Rung 16: a station shift must name its station.
    if staff_role in STATION_ROLES and obstacle_id is None:
        fail(
            "ERR_DIVISION_RULE_VIOLATION",
            "A %s shift must name the obstacle it covers." % staff_role,
        )

    # Rung 20: one human, one place, plus travel time.
    if calc.has_shift_conflict(staff_person_id, shift_start, shift_end):
        fail(
            "ERR_STAFF_SHIFT_CONFLICT",
            "Person %s already holds a confirmed shift within travel time." % staff_person_id,
        )

    row = db.insert(
        "staff_assignments",
        {
            "course_id": course["id"],
            "obstacle_id": obstacle_id,
            "staff_person_id": staff_person_id,
            "staff_role": staff_role,
            "certification_level": certification_level,
            "shift_start_utc": shift_start,
            "shift_end_utc": shift_end,
            "status": "CONFIRMED",
            "vacate_reason": None,
        },
    )

    if staff_role == "MARSHAL" and obstacle is not None:
        with db.mutation(obstacle) as station:
            calc.apply_obstacle_staffing(station, course)
    cascade.staffing_change_without_holdback(course)

    return common.created(row)


@bp.get("/ocr/staff-assignments")
def list_shifts():
    auth.require(
        auth.SAFETY_OFFICER, auth.RACE_DIRECTOR, auth.COURSE_DESIGNER, auth.OBSTACLE_MARSHAL
    )
    course_id = validation.query_str("course_id")
    obstacle_id = validation.query_str("obstacle_id")
    staff_person_id = validation.query_str("staff_person_id")
    status = validation.query_enum("status", validation.ASSIGNMENT_STATUSES)
    rows = db.all_rows("staff_assignments")
    if course_id is not None:
        rows = [r for r in rows if r["course_id"] == course_id]
    if obstacle_id is not None:
        rows = [r for r in rows if r["obstacle_id"] == obstacle_id]
    if staff_person_id is not None:
        rows = [r for r in rows if r["staff_person_id"] == staff_person_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.listing(rows)


@bp.get("/ocr/staff-assignments/<assignment_id>")
def read_shift(assignment_id):
    auth.require(
        auth.SAFETY_OFFICER, auth.RACE_DIRECTOR, auth.COURSE_DESIGNER, auth.OBSTACLE_MARSHAL
    )
    assignment = validation.path_assignment(assignment_id)
    return common.ok(assignment)


@bp.post("/ocr/staff-assignments/<assignment_id>/vacate")
def vacate_shift(assignment_id):
    auth.require(auth.SAFETY_OFFICER)
    assignment = validation.path_assignment(assignment_id)
    course = common.course_of(assignment)
    payload = validation.body()
    reason = validation.field_str(payload, "reason", 1)

    # Rung 9: a vacated shift cannot be vacated twice.
    if assignment["status"] != "CONFIRMED":
        fail("ERR_ASSIGNMENT_NOT_ACTIVE", "Shift %s reads %s." % (assignment["id"], assignment["status"]))

    with db.mutation(assignment) as row:
        row["status"] = "VACATED"
        row["vacate_reason"] = reason

    if assignment["staff_role"] == "MARSHAL" and assignment["obstacle_id"] is not None:
        obstacle = db.get("obstacles", assignment["obstacle_id"])
        if obstacle is not None:
            with db.mutation(obstacle) as station:
                calc.apply_obstacle_staffing(station, course)

    cascade.staffing_vacate_cascade(course)

    return common.ok(assignment)
