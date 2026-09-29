"""The thirteen pinned calculations of the domain.

Every non-integral intermediate is an exact Decimal; nothing here uses float.
Money is whole cents, ROUND_HALF_UP, quantized at exactly the step each rule
names.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from datetime import timedelta

# --- constants (calculations[].constants) ----------------------------------

TIER_4_FLOOR = 40000
TIER_3_FLOOR = 25000
TIER_2_FLOOR = 12000

SURCHARGE_TIER_3_FLOOR = 300
SURCHARGE_TIER_2_FLOOR = 150
SURCHARGE_TIER_1_FLOOR = 60
SURCHARGE_TIER_3_BP = 900
SURCHARGE_TIER_2_BP = 600
SURCHARGE_TIER_1_BP = 350

ROLLING_WINDOW_SIZE = 3
NO_SHOW_PENALTY = 25
LATE_PENALTY = 8
COMPLETED_CREDIT = 3
RELIABILITY_PROBATION_FLOOR = 65
LATE_GRACE_MINUTES = 5

REST_BUFFER_MINUTES = 30

OVERTIME_THRESHOLD_MINUTES = 480
OVERTIME_MULTIPLIER = Decimal("1.5")

REFUND_CAP_SUPERVISOR_CENTS = 5000
REFUND_CAP_DIRECTOR_CENTS = 50000
SEVERITY_UPLIFT_BP = {"CRITICAL": 5000, "HIGH": 2500, "MEDIUM": 0, "LOW": 0}
SEAT_RELOCATION_HARD_CAP_CENTS = 2500

SLA_MINUTES = {"CRITICAL": 5, "HIGH": 15, "MEDIUM": 45, "LOW": 120}
REOPEN_WINDOW_MINUTES = 1440

PROMOTER_SCORE_FLOOR = 4

FILL_RATE_UPLIFT_FLOOR_BP = 8000
UPLIFT_FACTOR = Decimal("1.10")
TRIM_FACTOR = Decimal("0.95")
TRIM_SATISFACTION_FLOOR = Decimal("4.5")

ONE = Decimal("1")


def cents(value):
    """Quantize an exact Decimal to whole cents, rounding half away from zero."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


# --- 1. event_attendance_tier ---------------------------------------------

def attendance_tier(attendance):
    if attendance >= TIER_4_FLOOR:
        return ("TIER_4", Decimal("1.45"))
    if attendance >= TIER_3_FLOOR:
        return ("TIER_3", Decimal("1.25"))
    if attendance >= TIER_2_FLOOR:
        return ("TIER_2", Decimal("1.10"))
    return ("TIER_1", Decimal("1.00"))


# --- 2. position_slot_required_headcount -----------------------------------

def ratio_headcount(basis_attendance, ratio_per_1000, min_headcount):
    """Quantize the ratio product to 4dp (half up) and only then ceiling it."""
    _, multiplier = attendance_tier(basis_attendance)
    raw = (
        Decimal(basis_attendance)
        / Decimal(1000)
        * Decimal(str(ratio_per_1000))
        * multiplier
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    derived = int(raw.to_integral_value(rounding=ROUND_CEILING))
    return max(derived, min_headcount)


# --- 3. staffing_plan_projected_labor_cost ---------------------------------

def slot_labor_cost(required_headcount, base_hourly_rate_cents, shift_minutes):
    return cents(
        Decimal(required_headcount)
        * Decimal(base_hourly_rate_cents)
        * Decimal(shift_minutes)
        / Decimal(60)
    )


def surcharge_bp(total_required_headcount):
    if total_required_headcount >= SURCHARGE_TIER_3_FLOOR:
        return SURCHARGE_TIER_3_BP
    if total_required_headcount >= SURCHARGE_TIER_2_FLOOR:
        return SURCHARGE_TIER_2_BP
    if total_required_headcount >= SURCHARGE_TIER_1_FLOOR:
        return SURCHARGE_TIER_1_BP
    return 0


def surcharge_cents(base_labor_cost_cents, bp):
    return cents(Decimal(base_labor_cost_cents) * Decimal(bp) / Decimal(10000))


# --- 4. staff_member_reliability_score ------------------------------------

def reliability_of(rows):
    """rows: assignment dicts, all in COMPLETED or NO_SHOW."""
    no_shows = sum(1 for a in rows if a["attendance_status"] == "NO_SHOW")
    completed = sum(1 for a in rows if a["attendance_status"] == "COMPLETED")
    lates = sum(
        1
        for a in rows
        if a["attendance_status"] == "COMPLETED" and a.get("late_check_in")
    )
    raw = (
        100
        - NO_SHOW_PENALTY * no_shows
        - LATE_PENALTY * lates
        + COMPLETED_CREDIT * completed
    )
    return max(0, min(100, raw))


# --- 6. assignment_worked_pay ---------------------------------------------

def worked_pay(worked_minutes, hourly_rate_cents):
    regular_minutes = min(worked_minutes, OVERTIME_THRESHOLD_MINUTES)
    overtime_minutes = max(worked_minutes - OVERTIME_THRESHOLD_MINUTES, 0)
    regular_cents = cents(
        Decimal(regular_minutes) * Decimal(hourly_rate_cents) / Decimal(60)
    )
    overtime_cents = cents(
        Decimal(overtime_minutes)
        * Decimal(hourly_rate_cents)
        / Decimal(60)
        * OVERTIME_MULTIPLIER
    )
    return regular_cents + overtime_cents


# --- 7. gratuity_pool_allocation ------------------------------------------

def gratuity_shares(pool, weights):
    """Floor each exact share, then hand the remainder out in ranking order."""
    total_weight = sum(weights)
    if not weights or total_weight == 0:
        return None
    floors = []
    for weight in weights:
        exact = Decimal(pool) * Decimal(weight) / Decimal(total_weight)
        floors.append(int(exact.to_integral_value(rounding=ROUND_FLOOR)))
    remainder = pool - sum(floors)
    for index in range(remainder):
        floors[index] += 1
    return floors


# --- 8. refund_authorized_amount ------------------------------------------

def effective_refund_cap(role, severity, category):
    role_cap = (
        REFUND_CAP_DIRECTOR_CENTS
        if role == "GuestExperienceDirector"
        else REFUND_CAP_SUPERVISOR_CENTS
    )
    uplift = cents(
        Decimal(role_cap) * Decimal(SEVERITY_UPLIFT_BP[severity]) / Decimal(10000)
    )
    cap = role_cap + uplift
    if category == "SEAT_RELOCATION":
        cap = min(cap, SEAT_RELOCATION_HARD_CAP_CENTS)
    return cap


# --- 9. guest_issue_sla ---------------------------------------------------

def sla_deadline(started_at, minutes):
    return started_at + timedelta(minutes=minutes)


# --- 10. accessibility_peak_occupancy -------------------------------------

def peak_occupancy(rows):
    """Largest concurrent units over half-open windows."""
    if not rows:
        return 0
    boundaries = sorted(
        {r["window_start"] for r in rows} | {r["window_end"] for r in rows}
    )
    best = 0
    for boundary in boundaries[:-1]:
        concurrent = sum(
            r["units_requested"]
            for r in rows
            if r["window_start"] <= boundary < r["window_end"]
        )
        if concurrent > best:
            best = concurrent
    return best


# --- 12. event_satisfaction_summary ---------------------------------------

def average_score(scores):
    if not scores:
        return None
    return (Decimal(sum(scores)) / Decimal(len(scores))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def promoter_share_bp(scores):
    if not scores:
        return None
    promoters = sum(1 for s in scores if s >= PROMOTER_SCORE_FLOOR)
    return int(
        (Decimal(promoters) * Decimal(10000) / Decimal(len(scores))).quantize(
            ONE, rounding=ROUND_HALF_UP
        )
    )


# --- 13. staffing_model_recommendation ------------------------------------

def fill_rate_bp(worked_headcount, planned_headcount):
    if planned_headcount == 0:
        return 0
    return int(
        (
            Decimal(worked_headcount) * Decimal(10000) / Decimal(planned_headcount)
        ).quantize(ONE, rounding=ROUND_HALF_UP)
    )


def recommended_ratio(ratio_per_1000, factor):
    return (Decimal(str(ratio_per_1000)) * factor).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
