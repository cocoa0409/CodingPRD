"""Outcome checkpoints and college credit grants (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint

import db
import middleware
import response
import timeutil
import validators
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_PARENT_STATE_CONFLICT,
    ApiError,
)
from routes.common import must_get, must_get_body, require_owner
from services import credit_svc

EMPLOYMENT_STATUSES = ("UNKNOWN", "EMPLOYED", "UNEMPLOYED", "ENROLLED_EDUCATION")
GRANT_STATUSES = ("PENDING", "GRANTED", "VOID")
GRANT_TARGETS = ("GRANTED", "VOID")
CREDIT_WINDOW_DAYS = 365
CREDIT_PHASES = ("INTERNSHIP", "COMPLETED")

bp = Blueprint("outcomes", __name__)


@bp.post("/outcome-checkpoints/<checkpoint_id>/records")
def record_checkpoint(checkpoint_id):
    actor = middleware.require(("Student",))
    checkpoint = must_get("outcome_checkpoints", checkpoint_id, "outcome checkpoint")
    data = validators.body()

    employment_status = validators.as_enum(data, "employment_status", EMPLOYMENT_STATUSES)
    hourly_wage_cents = validators.as_int(data, "hourly_wage_cents", required=False, default=None)
    recorded_at = validators.as_dt(data, "recorded_at", required=False, default=None)

    if employment_status == "EMPLOYED" and (hourly_wage_cents is None or int(hourly_wage_cents) <= 0):
        validators.fail("an EMPLOYED checkpoint must carry a positive hourly_wage_cents")

    require_owner(actor, checkpoint["student_id"], "outcome checkpoint %s" % checkpoint_id)

    checkpoint["employment_status"] = employment_status
    checkpoint["hourly_wage_cents"] = hourly_wage_cents
    checkpoint["recorded_at"] = recorded_at if recorded_at is not None else timeutil.now()
    db.touch(checkpoint)
    return response.success(checkpoint)


@bp.get("/students/<student_id>/outcome-checkpoints")
def list_outcome_checkpoints(student_id):
    middleware.require(("ProgramStaff", "Student"))
    must_get("students", student_id, "student")
    rows = [c for c in db.all_rows("outcome_checkpoints") if c["student_id"] == student_id]
    rows.sort(key=lambda c: (c["interval_months"], c["_seq"]))
    return response.list_response(rows)


@bp.post("/credit-grants")
def create_credit_grant():
    middleware.require(("ProgramStaff",))
    data = validators.body()

    raw_student_id = data.get("student_id")
    if not isinstance(raw_student_id, str) or not raw_student_id.strip():
        validators.fail("field 'student_id' is required")
    student = must_get_body("students", raw_student_id.strip(), "student_id")

    college_partner_name = validators.as_str(data, "college_partner_name")
    credit_hours = validators.as_number(data, "credit_hours")
    if float(credit_hours) <= 0:
        validators.fail("credit_hours must be greater than zero")

    row = db.make_row(
        student_id=student["id"],
        college_partner_name=college_partner_name,
        credit_hours=credit_hours,
        tuition_credit_cents=credit_svc.per_grant_tuition_credit(credit_hours),
        status="PENDING",
    )
    db.insert("credit_grants", row)
    return response.success(row, status=201)


@bp.get("/students/<student_id>/credit-grants")
def list_credit_grants(student_id):
    middleware.require(("ProgramStaff", "Student"))
    must_get("students", student_id, "student")
    status = validators.request_arg("status")
    rows = [g for g in db.all_rows("credit_grants") if g["student_id"] == student_id]
    if status:
        rows = [g for g in rows if g["status"] == status]
    return response.list_response(rows, key=response.by_created_at)


@bp.patch("/credit-grants/<grant_id>")
def advance_credit_grant(grant_id):
    middleware.require(("ProgramStaff",))
    grant = must_get("credit_grants", grant_id, "credit grant")
    data = validators.body()
    status = validators.as_enum(data, "status", GRANT_TARGETS)

    if grant["status"] in ("GRANTED", "VOID"):
        raise ApiError(
            ERR_ALREADY_TERMINAL,
            "credit grant %s is already %s" % (grant_id, grant["status"]),
            409,
        )

    if status == "GRANTED":
        student = db.get("students", grant["student_id"])
        phase_ok = student is not None and student.get("current_phase") in CREDIT_PHASES
        # The 365-day limit is measured from graduation; a student who has not
        # graduated yet has no deadline to exceed.
        window_ok = True
        if student is not None and student.get("graduation_at") is not None:
            deadline = student["graduation_at"] + timedelta(days=CREDIT_WINDOW_DAYS)
            window_ok = timeutil.today() <= deadline.date()
        if not (phase_ok and window_ok):
            raise ApiError(
                ERR_PARENT_STATE_CONFLICT,
                "the student is not in a phase or window that admits a GRANTED credit grant",
                409,
            )

    grant["status"] = status
    db.touch(grant)
    return response.success(grant)
