"""Stipend calculations and payment side effects (PRD 3.5)."""

import db
from services import cohort_svc, student_svc
from services.rounding import Decimal, round_cents, round_half_up

LND_WEEKLY_BASE_CENTS = 17500
BEHAVIOR_DEDUCTION_CENTS = 5000
BEHAVIOR_INCIDENT_THRESHOLD = 3
ATTENDANCE_DEDUCTION_DIVISOR = 10
POINTS_LND_BASE = 3
POINTS_LND_ATTENDANCE_BONUS = 2

INTERNSHIP_HOURLY_CENTS = 1650
INTERNSHIP_WEEKLY_HOURS_CAP = 25
ATTENDANCE_FLOOR_RATIO = Decimal("0.60")
ATTENDANCE_FLOOR_DEDUCTION_CENTS = 15000
INTERNSHIP_BEHAVIOR_DEDUCTION_CENTS = 7500
POINTS_INTERNSHIP_BASE = 6
POINTS_INTERNSHIP_ATTENDANCE_BONUS = 3

RATIO_SCALE = 4
ATTENDANCE_BONUS_RATIO = Decimal("0.95")
DISMISSAL_RATIO = Decimal("0.50")


def weeks_between(period_start, period_end):
    """Days from start to end divided by 7, round half up, never below 1."""
    days = (period_end.date() - period_start.date()).days
    weeks = round_half_up(Decimal(days) / Decimal(7), 0)
    return max(1, int(weeks))


def attendance_ratio(hours_attended, hours_expected):
    return round_half_up(Decimal(hours_attended) / Decimal(hours_expected), RATIO_SCALE)


def lnd_amounts(period_start, period_end, hours_attended, hours_expected, behavior_incidents):
    """L&D-phase statement; the pinned proportional-absence variant."""
    weeks = weeks_between(period_start, period_end)
    gross = weeks * LND_WEEKLY_BASE_CENTS
    ratio = attendance_ratio(hours_attended, hours_expected)
    absence_ratio = Decimal(1) - ratio
    attendance_deduction = round_cents(
        Decimal(gross) * absence_ratio / Decimal(ATTENDANCE_DEDUCTION_DIVISOR)
    )
    behavior_deduction = (
        BEHAVIOR_DEDUCTION_CENTS if behavior_incidents >= BEHAVIOR_INCIDENT_THRESHOLD else 0
    )
    net = max(0, gross - attendance_deduction - behavior_deduction)
    points = POINTS_LND_BASE + (POINTS_LND_ATTENDANCE_BONUS if ratio >= ATTENDANCE_BONUS_RATIO else 0)
    return {
        "attendance_ratio": ratio,
        "gross_amount_cents": gross,
        "attendance_deduction_cents": attendance_deduction,
        "behavior_deduction_cents": behavior_deduction,
        "net_amount_cents": net,
        "contract_points_earned": points,
    }


def internship_amounts(period_start, period_end, hours_attended, hours_expected, behavior_incidents):
    """Internship-phase statement; hours are capped at the weekly ceiling."""
    weeks = weeks_between(period_start, period_end)
    weekly_hours = int(round_half_up(Decimal(hours_expected) / Decimal(weeks), 0))
    billable_hours = weeks * min(weekly_hours, INTERNSHIP_WEEKLY_HOURS_CAP)
    gross = billable_hours * INTERNSHIP_HOURLY_CENTS
    ratio = attendance_ratio(hours_attended, hours_expected)
    proportional = round_cents(Decimal(gross) * (Decimal(1) - ratio))
    floor_deduction = ATTENDANCE_FLOOR_DEDUCTION_CENTS if ratio < ATTENDANCE_FLOOR_RATIO else 0
    attendance_deduction = proportional + floor_deduction
    behavior_deduction = (
        INTERNSHIP_BEHAVIOR_DEDUCTION_CENTS
        if behavior_incidents >= BEHAVIOR_INCIDENT_THRESHOLD
        else 0
    )
    net = max(0, gross - attendance_deduction - behavior_deduction)
    points = POINTS_INTERNSHIP_BASE + (
        POINTS_INTERNSHIP_ATTENDANCE_BONUS if ratio >= ATTENDANCE_BONUS_RATIO else 0
    )
    return {
        "attendance_ratio": ratio,
        "gross_amount_cents": gross,
        "attendance_deduction_cents": attendance_deduction,
        "behavior_deduction_cents": behavior_deduction,
        "net_amount_cents": net,
        "contract_points_earned": points,
    }


def compute_amounts(phase, period_start, period_end, hours_attended, hours_expected, incidents):
    if phase == "L_AND_D":
        return lnd_amounts(period_start, period_end, hours_attended, hours_expected, incidents)
    return internship_amounts(period_start, period_end, hours_attended, hours_expected, incidents)


def apply_payment(statement):
    """Credit the student, re-evaluate roster standing and advance the phase."""
    student = db.get("students", statement["student_id"])
    if student is None:
        return None

    student["total_stipend_paid_cents"] = int(student.get("total_stipend_paid_cents") or 0) + int(
        statement["net_amount_cents"]
    )
    student["lifetime_contract_points"] = int(student.get("lifetime_contract_points") or 0) + int(
        statement["contract_points_earned"]
    )

    ratio = statement["attendance_ratio"]
    if ratio < DISMISSAL_RATIO:
        student["roster_status"] = "DISMISSED"
    elif int(student["lifetime_contract_points"]) < student_svc.LND_POINTS_THRESHOLD:
        student["roster_status"] = "PROBATION"
    db.touch(student)

    student_svc.maybe_advance_to_internship(student)
    cohort_svc.recompute_for_student(student)
    return student


def apply_void(statement):
    """A voided statement stops contributing to every total."""
    student = db.get("students", statement["student_id"])
    cohort_svc.recompute_for_student(student)
    return student
