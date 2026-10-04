"""Student intake, selection and enrollment (PRD 3.1, 3.2)."""

from flask import Blueprint

import db
import middleware
import response
import timeutil
import validators
from errors import (
    ERR_CAPACITY_EXCEEDED,
    ERR_DUPLICATE_EMAIL,
    ERR_INVALID_STATE,
    ERR_PARENT_STATE_CONFLICT,
    ApiError,
)
from routes.common import must_get, must_get_body, terminal
from services import student_svc

TRACK_CODES = ("SOFTWARE", "DATA", "CYBER", "IT_SUPPORT")
EDUCATION_STATUSES = ("NO_DIPLOMA", "HS_DIPLOMA", "SOME_COLLEGE", "ASSOCIATE", "BACHELOR_OR_HIGHER")

bp = Blueprint("students", __name__)


def _new_student_row(full_name, email, date_of_birth, education_status, household_income_cents):
    return db.make_row(
        full_name=full_name,
        email=email,
        date_of_birth=date_of_birth,
        education_status=education_status,
        household_income_cents=household_income_cents,
        application_state="APPLIED",
        current_phase=None,
        track_code=None,
        cohort_id=None,
        graduation_at=None,
        total_stipend_paid_cents=0,
        lifetime_contract_points=0,
        conversion_streak=0,
        roster_status="ON_TRACK",
    )


@bp.post("/students")
def register_student():
    """Anonymous registration: the one operation that needs no credentials."""
    middleware.require(("Anonymous",), allow_anonymous=True)
    data = validators.body()
    full_name = validators.as_str(data, "full_name")
    email = validators.as_str(data, "email")
    date_of_birth = validators.as_dt(data, "date_of_birth")
    education_status = validators.as_enum(data, "education_status", EDUCATION_STATUSES)
    household_income_cents = validators.as_int(data, "household_income_cents")

    for existing in db.all_rows("students"):
        if existing["email"] == email:
            raise ApiError(ERR_DUPLICATE_EMAIL, "email '%s' is already registered" % email, 409)

    row = _new_student_row(full_name, email, date_of_birth, education_status, household_income_cents)
    db.insert("students", row)
    return response.success(row, status=201)


@bp.get("/students/<student_id>")
def read_student(student_id):
    middleware.require(("ProgramStaff", "Student"))
    student = must_get("students", student_id, "student")
    return response.success(student)


@bp.post("/students/<student_id>/eligibility-decisions")
def eligibility_decision(student_id):
    middleware.require(("ProgramStaff",))
    student = must_get("students", student_id, "student")
    data = validators.body()
    decision = validators.as_enum(data, "decision", ("ELIGIBLE", "INELIGIBLE"))

    state = student["application_state"]
    if state == "INELIGIBLE":
        terminal("student %s is already INELIGIBLE" % student_id)
    if state != "APPLIED":
        raise ApiError(
            ERR_INVALID_STATE,
            "a selection decision is only admissible while the student is APPLIED",
            409,
        )

    if decision == "ELIGIBLE":
        student_svc.check_eligibility_gates(student)
        student["application_state"] = "ELIGIBLE"
    else:
        student["application_state"] = "INELIGIBLE"
    db.touch(student)
    return response.success(student)


@bp.post("/students/<student_id>/enrollments")
def enroll_student(student_id):
    middleware.require(("ProgramStaff",))
    student = must_get("students", student_id, "student")

    data = validators.body()
    raw_cohort_id = data.get("cohort_id")
    if not isinstance(raw_cohort_id, str) or not raw_cohort_id.strip():
        validators.fail("field 'cohort_id' is required")
    cohort = must_get_body("cohorts", raw_cohort_id.strip(), "cohort_id")
    track_code = validators.as_enum(data, "track_code", TRACK_CODES)

    state = student["application_state"]
    if state == "INELIGIBLE":
        terminal("student %s is INELIGIBLE and can never be enrolled" % student_id)
    if state != "ELIGIBLE":
        raise ApiError(
            ERR_INVALID_STATE,
            "enrollment requires an ELIGIBLE student; current state is %s" % state,
            409,
        )

    if cohort["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "cohort %s is %s and no longer admits enrollment" % (cohort["id"], cohort["status"]),
            409,
        )
    if timeutil.today() > cohort["graduation_date"].date():
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "the cohort's graduation date has already passed on the logical clock",
            409,
        )
    if cohort["program_code"] != track_code:
        raise ApiError(
            ERR_PARENT_STATE_CONFLICT,
            "track_code %s does not match the cohort's program_code %s"
            % (track_code, cohort["program_code"]),
            409,
        )

    student_svc.check_eligibility_gates(student)

    if int(cohort["enrolled_count"]) >= int(cohort["capacity"]):
        raise ApiError(
            ERR_CAPACITY_EXCEEDED,
            "cohort %s has no free seat" % cohort["id"],
            409,
        )

    student["application_state"] = "ENROLLED"
    student["current_phase"] = "L_AND_D"
    student["track_code"] = track_code
    student["cohort_id"] = cohort["id"]
    db.touch(student)

    cohort["enrolled_count"] = int(cohort["enrolled_count"]) + 1
    if cohort["status"] == "PLANNED":
        cohort["status"] = "ACTIVE"
    db.touch(cohort)

    return response.success(student)
