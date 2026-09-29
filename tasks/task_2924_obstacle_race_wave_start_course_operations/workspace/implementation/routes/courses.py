"""Courses (PRD 3.2): layout, the design gate and publication."""

from flask import Blueprint

import auth
import db
import validation
from errors import fail
from routes import common
from services import calc

bp = Blueprint("courses", __name__)


@bp.post("/ocr/venues/<venue_id>/courses")
def create_course(venue_id):
    auth.require(auth.COURSE_DESIGNER)
    venue = validation.path_venue(venue_id)
    payload = validation.body()
    name = validation.field_str(payload, "name", 1, 120)
    distance = validation.field_int(payload, "total_distance_m", minimum=1)
    corral_rate = validation.field_decimal(payload, "corral_release_rate_per_min", exclusive_min=0)
    corral_capacity = validation.field_int(payload, "corral_throughput_capacity", minimum=1)

    common.require_venue_open(venue)

    row = db.insert(
        "courses",
        {
            "venue_id": venue["id"],
            "name": name,
            "total_distance_m": distance,
            "corral_release_rate_per_min": calc.round2(corral_rate),
            "corral_throughput_capacity": corral_capacity,
            "status": "DRAFT",
            "readiness_posture": "RESTRICTED",
            "obstacle_count": 0,
            "difficulty_progression_score": calc.round2(0),
            "design_capacity_pph": 0,
            "bottleneck_capacity_pph": 0,
            "medic_headcount": 0,
            "water_safety_headcount": 0,
            "scheduled_capacity_total": 0,
        },
    )
    return common.created(row)


@bp.get("/ocr/venues/<venue_id>/courses")
def list_courses(venue_id):
    auth.require(*auth.OPERATOR_READERS)
    venue = validation.path_venue(venue_id)
    status = validation.query_enum("status", validation.COURSE_STATUSES)
    rows = db.where("courses", venue_id=venue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.listing(rows)


@bp.get("/ocr/courses/<course_id>")
def read_course(course_id):
    auth.require(*auth.OPERATOR_READERS, auth.OBSTACLE_MARSHAL)
    course = validation.path_course(course_id)
    return common.ok(course)


@bp.post("/ocr/courses/<course_id>/validate")
def validate_course(course_id):
    auth.require(auth.COURSE_DESIGNER)
    course = validation.path_course(course_id)
    venue = common.venue_of(course)

    # Rung 9: state first, then the parcel posture (PRD 3.2 lists them so).
    if course["status"] != "DRAFT":
        fail("ERR_COURSE_STATE_INVALID", "A %s course cannot be validated." % course["status"])
    common.require_venue_open(venue)

    # Rung 23 then 24: a governing permit, and water permission under it.
    permit = common.governing_permit_or_fail(venue)
    if not permit["water_use_allowed"]:
        for obstacle in calc.obstacles_of_course(course["id"]):
            if obstacle["water_contact"]:
                fail(
                    "ERR_WATER_USE_NOT_PERMITTED",
                    "Obstacle %s enters water but the permit forbids it." % obstacle["id"],
                )

    # Rung 25: the three design-gate refusals (422).
    primaries = calc.primary_obstacles(course["id"])
    score, regressions = calc.progression(course)
    if len(primaries) < calc.MIN_OBSTACLES:
        fail(
            "ERR_COURSE_TOO_SHORT",
            "A course needs at least %d primary obstacles." % calc.MIN_OBSTACLES,
        )
    if score < calc.MIN_PROGRESSION_SCORE:
        fail(
            "ERR_PROGRESSION_TOO_FLAT",
            "difficulty_progression_score %s is below the %s minimum."
            % (score, calc.MIN_PROGRESSION_SCORE),
        )
    if regressions > 0:
        fail(
            "ERR_PROGRESSION_REGRESSION",
            "%d consecutive station pair(s) drop by more than %d points."
            % (regressions, calc.MAX_REGRESSION),
        )

    # Rung 29: the parcel's disturbance must fit the permit's cap (equality passes).
    if int(venue["disturbed_area_sqm"]) > int(permit["max_disturbed_area_sqm"]):
        fail(
            "ERR_DISTURBED_AREA_EXCEEDED",
            "Disturbed area %d exceeds the permitted %d."
            % (int(venue["disturbed_area_sqm"]), int(permit["max_disturbed_area_sqm"])),
        )

    with db.mutation(course) as row:
        row["status"] = "VALIDATED"
        calc.apply_course_design_fields(row)
        calc.apply_readiness(row)
    return common.ok(course)


@bp.post("/ocr/courses/<course_id>/publish")
def publish_course(course_id):
    auth.require(auth.RACE_DIRECTOR)
    course = validation.path_course(course_id)
    venue = common.venue_of(course)

    if course["status"] != "VALIDATED":
        fail("ERR_COURSE_STATE_INVALID", "A %s course cannot be published." % course["status"])
    common.require_venue_open(venue)
    if calc.readiness_for(course) == "FROZEN":
        fail("ERR_COURSE_UNSAFE", "Course %s reads a frozen readiness posture." % course["id"])

    with db.mutation(course) as row:
        row["status"] = "PUBLISHED"
        calc.apply_readiness(row)
    return common.ok(course)
