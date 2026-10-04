"""Stipend statement creation and listing (PRD 3.5)."""

from flask import Blueprint

import db
import middleware
import response
import validators
from errors import (
    ERR_PARENT_STATE_CONFLICT,
    ERR_STIPEND_PERIOD_OVERLAP,
    ApiError,
)
from routes.common import must_get, must_get_body, terminal
from services import stipend_svc

PHASES = ("L_AND_D", "INTERNSHIP")
MIN_PERIOD_DAYS = 7
DEFAULT_BEHAVIOR_INCIDENTS = 0

bp = Blueprint("stipends", __name__)


def _periods_overlap(start_a, end_a, start_b, end_b):
    """Inclusive periods overlap when they share at least one calendar day."""
    return not (end_a.date() < start_b.date() or end_b.date() < start_a.date())


@bp.post("/stipend-statements")
def create_stipend_statement():
    middleware.require(("ProgramStaff",))
    data = validators.body()

    raw_student_id = data.get("student_id")
    if not isinstance(raw_student_id, str) or not raw_student_id.strip():
        validators.fail("field 'student_id' is required")
    student = must_get_body("students", raw_student_id.strip(), "student_id")

    phase = validators.as_enum(data, "phase", PHASES)
    period_start = validators.as_dt(data, "period_start")
    period_end = validators.as_dt(data, "period_end")
    hours_attended = validators.as_int(data, "hours_attended")
    hours_expected = validators.as_int(data, "hours_expected")
    behavior_incidents = validators.as_int(
        data, "behavior_incidents", required=False, default=DEFAULT_BEHAVIOR_INCIDENTS
    )

    if int(hours_expected) <= 0:
        validators.fail("hours_expected must be greater than zero")
    if (period_end.date() - period_start.date()).days < MIN_PERIOD_DAYS:
        validators.fail("period_end must be at least %d days after period_start" % MIN_PERIOD_DAYS)

    if student["application_state"] == "INELIGIBLE":
        terminal("student %s is INELIGIBLE and no stipend statement may be created" % student["id"])

    if phase == "INTERNSHIP":
        running = [
            p for p in db.all_rows("placements")
            if p["student_id"] == student["id"] and p["state"] in ("ACCEPTED", "ACTIVE")
        ]
        if not running:
            raise ApiError(
                ERR_PARENT_STATE_CONFLICT,
                "an INTERNSHIP-phase statement requires a placement at ACCEPTED or ACTIVE",
                409,
            )

    for existing in db.all_rows("stipend_statements"):
        if (
            existing["student_id"] == student["id"]
            and existing["phase"] == phase
            and existing["status"] in ("PENDING", "PAID")
            and _periods_overlap(
                period_start, period_end, existing["period_start"], existing["period_end"]
            )
        ):
            raise ApiError(
                ERR_STIPEND_PERIOD_OVERLAP,
                "the period overlaps statement %s" % existing["id"],
                409,
            )

    amounts = stipend_svc.compute_amounts(
        phase, period_start, period_end, int(hours_attended), int(hours_expected),
        int(behavior_incidents),
    )

    row = db.make_row(
        student_id=student["id"],
        phase=phase,
        period_start=period_start,
        period_end=period_end,
        hours_attended=int(hours_attended),
        hours_expected=int(hours_expected),
        behavior_incidents=int(behavior_incidents),
        status="PENDING",
        **amounts
    )
    db.insert("stipend_statements", row)
    return response.success(row, status=201)


@bp.get("/students/<student_id>/stipend-statements")
def list_student_stipends(student_id):
    middleware.require(("ProgramStaff", "Student"))
    must_get("students", student_id, "student")
    phase = validators.request_arg("phase")
    status = validators.request_arg("status")

    rows = [s for s in db.all_rows("stipend_statements") if s["student_id"] == student_id]
    if phase:
        rows = [s for s in rows if s["phase"] == phase]
    if status:
        rows = [s for s in rows if s["status"] == status]
    return response.list_response(rows, key=response.by_created_at)
