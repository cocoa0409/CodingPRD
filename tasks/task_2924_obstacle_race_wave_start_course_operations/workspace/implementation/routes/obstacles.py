"""Obstacles (PRD 3.2): station placement, the two clearance readings, attempt roll."""

from flask import Blueprint

import auth
import db
import validation
from errors import fail
from routes import common
from services import calc

bp = Blueprint("obstacles", __name__)


@bp.post("/ocr/courses/<course_id>/obstacles")
def place_obstacle(course_id):
    auth.require(auth.COURSE_DESIGNER)
    course = validation.path_course(course_id)
    venue = common.venue_of(course)
    payload = validation.body()
    name = validation.field_str(payload, "name", 1, 80)
    station_index = validation.field_int(payload, "station_index", minimum=1)
    difficulty = validation.field_int(payload, "difficulty_rating", minimum=1, maximum=10)
    lane_count = validation.field_int(payload, "lane_count", minimum=1)
    service_rate = validation.field_decimal(payload, "service_rate_per_min", exclusive_min=0)
    marshals_required = validation.field_int(payload, "marshals_required", minimum=1)
    footprint = validation.field_int(payload, "footprint_sqm", minimum=1)
    water_contact = validation.field_bool(payload, "water_contact")
    bypass_mode = validation.field_enum(payload, "bypass_mode", validation.BYPASS_MODES)
    penalty_seconds = validation.field_int(payload, "penalty_seconds", minimum=0)
    paired_id = validation.field_id(payload, "paired_obstacle_id", default=None)

    # Rung 5: a bypass lane must relieve a primary standing on this same course.
    if paired_id is not None:
        validation.fk_obstacle(paired_id, course_id=course["id"])

    # Rung 9: the station set freezes the moment the course leaves DRAFT.
    if course["status"] != "DRAFT":
        fail("ERR_OBSTACLE_SET_FROZEN", "Course %s is no longer a draft." % course["id"])
    common.require_venue_open(venue)

    # Rung 22: station_index is unique per course.
    for peer in calc.obstacles_of_course(course["id"]):
        if int(peer["station_index"]) == station_index:
            fail(
                "ERR_STATION_INDEX_CONFLICT",
                "Station index %d is already used on this course." % station_index,
            )

    row = db.insert(
        "obstacles",
        {
            "course_id": course["id"],
            "paired_obstacle_id": paired_id,
            "name": name,
            "station_index": station_index,
            "difficulty_rating": difficulty,
            "lane_count": lane_count,
            "service_rate_per_min": calc.round2(service_rate),
            "marshals_required": marshals_required,
            "footprint_sqm": footprint,
            "water_contact": water_contact,
            "bypass_mode": bypass_mode,
            "penalty_seconds": penalty_seconds,
            "confirmed_marshal_count": 0,
            "staffing_state": "UNSTAFFED",
            "design_clearance_rate_per_min": calc.round2(0),
            "effective_clearance_rate_per_min": calc.round2(0),
        },
    )
    calc.apply_obstacle_rates(row, course)

    with db.mutation(course) as parent:
        calc.apply_course_design_fields(parent)
        calc.apply_bottleneck(parent)
    with db.mutation(venue) as parcel:
        calc.apply_disturbed_area(parcel)

    return common.created(row)


@bp.get("/ocr/obstacles")
def list_obstacles():
    auth.require(*auth.OPERATOR_READERS, auth.OBSTACLE_MARSHAL)
    course_id = validation.query_str("course_id")
    paired_id = validation.query_str("paired_obstacle_id")
    staffing_state = validation.query_enum("staffing_state", validation.STAFFING_STATES)
    rows = db.all_rows("obstacles")
    if course_id is not None:
        rows = [r for r in rows if r["course_id"] == course_id]
    if paired_id is not None:
        rows = [r for r in rows if r["paired_obstacle_id"] == paired_id]
    if staffing_state is not None:
        rows = [r for r in rows if r["staffing_state"] == staffing_state]
    return common.listing(rows)


@bp.get("/ocr/obstacles/<obstacle_id>")
def read_obstacle(obstacle_id):
    auth.require(*auth.OPERATOR_READERS, auth.OBSTACLE_MARSHAL)
    obstacle = validation.path_obstacle(obstacle_id)
    return common.ok(obstacle)


@bp.get("/ocr/obstacles/<obstacle_id>/attempts")
def list_obstacle_attempts(obstacle_id):
    auth.require(
        auth.RACE_DIRECTOR, auth.SAFETY_OFFICER, auth.OBSTACLE_MARSHAL, auth.COURSE_DESIGNER
    )
    obstacle = validation.path_obstacle(obstacle_id)
    outcome = validation.query_enum("outcome", validation.ATTEMPT_OUTCOMES)
    rows = db.where("attempts", obstacle_id=obstacle["id"])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    rows = sorted(rows, key=lambda a: (a["recorded_at"], a["created_at"], a["_seq"]))
    return common.listing(rows)
