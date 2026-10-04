"""Eligibility gates, L&D progression and the graduation cascade
(PRD 2.11, 3.1, 3.2, 3.6, 3.8)."""

import db
import timeutil
from errors import (
    ERR_AGE_INELIGIBLE,
    ERR_EDUCATION_INELIGIBLE,
    ERR_INCOME_INELIGIBLE,
    ApiError,
)
from services import cohort_svc

AGE_MIN = 18
AGE_MAX = 24
INCOME_CEILING_CENTS = 4500000
QUALIFYING_EDUCATION = ("NO_DIPLOMA", "HS_DIPLOMA", "SOME_COLLEGE", "ASSOCIATE")
LND_POINTS_THRESHOLD = 12
NON_TERMINAL_PLACEMENT_STATES = (
    "MATCHED",
    "INTERVIEW_SCHEDULED",
    "INTERVIEWED",
    "OFFERED",
    "ACCEPTED",
    "ACTIVE",
)
CHECKPOINT_INTERVALS = (3, 6, 12)


def check_eligibility_gates(student):
    """Checks 10-12, evaluated in that fixed order."""
    reference = timeutil.today()
    age = timeutil.age_on(student["date_of_birth"].date(), reference)
    if age < AGE_MIN or age > AGE_MAX:
        raise ApiError(
            ERR_AGE_INELIGIBLE,
            "student must be between %d and %d years old at the logical-clock date"
            % (AGE_MIN, AGE_MAX),
            422,
        )
    if student["education_status"] not in QUALIFYING_EDUCATION:
        raise ApiError(
            ERR_EDUCATION_INELIGIBLE,
            "education_status %s does not qualify" % student["education_status"],
            422,
        )
    if int(student["household_income_cents"]) > INCOME_CEILING_CENTS:
        raise ApiError(
            ERR_INCOME_INELIGIBLE,
            "household income exceeds the %d cent ceiling" % INCOME_CEILING_CENTS,
            422,
        )


def has_paid_lnd_statement(student_id):
    for statement in db.all_rows("stipend_statements"):
        if (
            statement["student_id"] == student_id
            and statement["phase"] == "L_AND_D"
            and statement["status"] == "PAID"
        ):
            return True
    return False


def maybe_advance_to_internship(student):
    """L_AND_D -> INTERNSHIP once 12 contract points are reached (PRD 3.2)."""
    if student is None or student.get("current_phase") != "L_AND_D":
        return False
    if int(student.get("lifetime_contract_points") or 0) < LND_POINTS_THRESHOLD:
        return False
    if student.get("roster_status") == "DISMISSED":
        return False
    if not has_paid_lnd_statement(student["id"]):
        return False
    student["current_phase"] = "INTERNSHIP"
    db.touch(student)
    cohort_svc.maybe_complete_cohort(db.get("cohorts", student.get("cohort_id")))
    return True


def placements_of(student_id):
    return [p for p in db.all_rows("placements") if p["student_id"] == student_id]


def create_outcome_checkpoints(student, graduation_at):
    created = []
    for interval in CHECKPOINT_INTERVALS:
        row = db.make_row(
            student_id=student["id"],
            interval_months=interval,
            due_date=timeutil.add_months(graduation_at, interval),
            employment_status="UNKNOWN",
            hourly_wage_cents=None,
            recorded_at=None,
        )
        created.append(db.insert("outcome_checkpoints", row))
    return created


def maybe_graduate(student):
    """Graduate when a completion leaves no non-terminal placement behind."""
    if student is None or student.get("current_phase") != "INTERNSHIP":
        return False
    placements = placements_of(student["id"])
    if any(p["state"] in NON_TERMINAL_PLACEMENT_STATES for p in placements):
        return False
    if not any(p["state"] == "COMPLETED" for p in placements):
        return False
    graduation_at = timeutil.now()
    student["current_phase"] = "COMPLETED"
    student["graduation_at"] = graduation_at
    db.touch(student)
    create_outcome_checkpoints(student, graduation_at)
    cohort_svc.maybe_complete_cohort(db.get("cohorts", student.get("cohort_id")))
    return True


def has_non_terminal_placement(student_id, exclude_placement_id=None):
    for placement in placements_of(student_id):
        if placement["id"] == exclude_placement_id:
            continue
        if placement["state"] in NON_TERMINAL_PLACEMENT_STATES:
            return True
    return False


def has_active_placement(student_id, exclude_placement_id=None):
    for placement in placements_of(student_id):
        if placement["id"] == exclude_placement_id:
            continue
        if placement["state"] in ("ACCEPTED", "ACTIVE"):
            return True
    return False
