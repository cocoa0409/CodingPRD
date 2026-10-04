"""Learning-and-development cohorts (PRD 3.2)."""

from flask import Blueprint

import db
import middleware
import response
import timeutil
import validators
from routes.common import must_get

TRACK_CODES = ("SOFTWARE", "DATA", "CYBER", "IT_SUPPORT")
DEFAULT_CAPACITY = 24
GRADUATION_DAYS = 180

bp = Blueprint("cohorts", __name__)


@bp.post("/cohorts")
def create_cohort():
    middleware.require(("ProgramStaff",))
    data = validators.body()
    program_code = validators.as_enum(data, "program_code", TRACK_CODES)
    location_code = validators.as_str(data, "location_code")
    start_date = validators.as_dt(data, "start_date")
    capacity = validators.as_int(data, "capacity", required=False, default=DEFAULT_CAPACITY)

    row = db.make_row(
        program_code=program_code,
        location_code=location_code,
        start_date=start_date,
        capacity=capacity,
        enrolled_count=0,
        graduation_date=timeutil.add_days(start_date, GRADUATION_DAYS),
        awarded_points=0,
        status="PLANNED",
    )
    db.insert("cohorts", row)
    return response.success(row, status=201)


@bp.get("/cohorts/<cohort_id>")
def read_cohort(cohort_id):
    middleware.require(("ProgramStaff", "Student"))
    cohort = must_get("cohorts", cohort_id, "cohort")
    return response.success(cohort)


@bp.get("/cohorts/<cohort_id>/students")
def list_cohort_students(cohort_id):
    middleware.require(("ProgramStaff",))
    must_get("cohorts", cohort_id, "cohort")
    rows = [
        s for s in db.all_rows("students")
        if s.get("cohort_id") == cohort_id and s["application_state"] == "ENROLLED"
    ]
    return response.list_response(rows, key=response.by_created_at)
