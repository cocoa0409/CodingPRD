"""Cohort contract-point award and lifecycle (PRD 3.2, scaffold
`cohort_contract_points`).

The level is read from the raw total; the base award is derived from that same
raw total, so the value is never self-referential.
"""

import db
from services.rounding import Decimal, round_half_up

LEVEL_2_MIN = 10
LEVEL_3_MIN = 20
LEVEL_BONUS_MULTIPLIER = 100


def enrolled_students(cohort_id):
    return [
        s for s in db.all_rows("students")
        if s.get("cohort_id") == cohort_id and s["application_state"] == "ENROLLED"
    ]


def total_lnd_points(cohort_id):
    total = 0
    for statement in db.all_rows("stipend_statements"):
        if statement["status"] != "PAID" or statement["phase"] != "L_AND_D":
            continue
        student = db.get("students", statement["student_id"])
        if student is not None and student.get("cohort_id") == cohort_id:
            total += int(statement["contract_points_earned"] or 0)
    return total


def compute_awarded_points(cohort_id):
    total_points = total_lnd_points(cohort_id)
    if total_points >= LEVEL_3_MIN:
        level = 3
    elif total_points >= LEVEL_2_MIN:
        level = 2
    else:
        level = 1
    base_points = int(round_half_up(Decimal(total_points) / Decimal(3), 0))
    return base_points + level * LEVEL_BONUS_MULTIPLIER


def recompute_awarded_points(cohort):
    if cohort is None:
        return None
    value = compute_awarded_points(cohort["id"])
    if cohort.get("awarded_points") != value:
        cohort["awarded_points"] = value
        db.touch(cohort)
    return cohort


def recompute_for_student(student):
    if student is None:
        return None
    cohort = db.get("cohorts", student.get("cohort_id"))
    if cohort is None:
        return None
    return recompute_awarded_points(cohort)


def maybe_complete_cohort(cohort):
    """COMPLETED once every enrolled student is at INTERNSHIP or COMPLETED."""
    if cohort is None or cohort["status"] == "COMPLETED":
        return cohort
    students = enrolled_students(cohort["id"])
    if not students:
        return cohort
    if all(s.get("current_phase") in ("INTERNSHIP", "COMPLETED") for s in students):
        cohort["status"] = "COMPLETED"
        db.touch(cohort)
    return cohort
