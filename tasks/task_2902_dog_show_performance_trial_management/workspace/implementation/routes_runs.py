"""Performance runs: append-only score sheets for agility, obedience, rally."""
from flask import Blueprint

import agg
from auth import authenticate, must_get
import calc
from common import ALL_ROLES
from envelope import list_response, object_response
from errors import fail
import shape
import store
from store import set_fields

bp = Blueprint("runs", __name__)


@bp.post("/performance-runs")
def record_run():
    authenticate(["Judge"])
    body = shape.json_body()
    entry_id = shape.string_field(body, "entry_id")
    course_yardage_m = shape.number_field(body, "course_yardage_m",
                                          exclusive_minimum=0)
    standard_course_time_s = shape.number_field(body, "standard_course_time_s",
                                                exclusive_minimum=0)
    actual_time_s = shape.number_field(body, "actual_time_s", minimum=0)
    faults_count = shape.int_field(body, "faults_count", required=False,
                                   default=0, minimum=0)
    refusals_count = shape.int_field(body, "refusals_count", required=False,
                                     default=0, minimum=0)
    obedience_deductions = shape.number_field(body, "obedience_deductions",
                                              required=False, default=0,
                                              minimum=0)

    entry = must_get("entries", entry_id)
    cls = store.get("classes", entry["class_id"])
    show = store.get("shows", entry["show_id"])

    if agg.heat_blocked(show, cls):
        fail("ERR_HEAT_RESTRICTION_ACTIVE",
             "A RED advisory blocks performance runs at an outdoor show.")

    if cls["class_level"] != "PERFORMANCE":
        fail("ERR_COURSE_DESIGN_INVALID",
             "A run may only be recorded against a PERFORMANCE entry.")
    if entry["entry_status"] != "CHECKED_IN":
        fail("ERR_COURSE_DESIGN_INVALID",
             "The entry is %s rather than CHECKED_IN." % entry["entry_status"])
    discipline = cls["discipline"]
    if discipline == "AGILITY":
        floor_s = calc.agility_min_standard_time(course_yardage_m)
        if standard_course_time_s < floor_s:
            fail("ERR_COURSE_DESIGN_INVALID",
                 "standard_course_time_s must be at least %s seconds." % floor_s)

    scored = calc.score_run(
        discipline, faults_count, refusals_count, obedience_deductions,
        actual_time_s, standard_course_time_s,
    )
    rec = store.insert("runs", {
        "entry_id": entry_id,
        "discipline": discipline,
        "course_yardage_m": course_yardage_m,
        "standard_course_time_s": standard_course_time_s,
        "actual_time_s": actual_time_s,
        "faults_count": faults_count,
        "refusals_count": refusals_count,
        "obedience_deductions": obedience_deductions,
        "time_faults": scored["time_faults"],
        "total_faults": scored["total_faults"],
        "final_score": scored["final_score"],
        "run_result": scored["run_result"],
        "title_leg_awarded": scored["title_leg_awarded"],
    }, versioned=False)

    if scored["title_leg_awarded"]:
        dog = store.get("dogs", entry["dog_id"])
        counts = dict(dog["qualifying_leg_counts"])
        counts[discipline] = counts.get(discipline, 0) + 1
        set_fields(dog, qualifying_leg_counts=counts)
    return object_response(store.serialize(rec), 201)


@bp.get("/entries/<entry_id>/performance-runs")
def list_runs(entry_id):
    authenticate(ALL_ROLES)
    must_get("entries", entry_id)
    limit, offset = shape.pagination()
    rows = [r for r in store.rows("runs") if r["entry_id"] == entry_id]
    items, total = shape.paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)
