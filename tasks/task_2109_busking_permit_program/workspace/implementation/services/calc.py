"""The eleven calculation rules of the program (PRD sections 3.1 - 3.9).

Every figure here is derived exactly as the PRD states, with the rounding
applied at the step where it appears rather than once at the end.
"""
from datetime import timedelta
from decimal import Decimal

from utils import (add_days, is_weekend, minute_of_day, rhu_2dp, rhu_int,
                   whole_minutes)

# ------------------------------------------------------------------ constants
BASE_FEE_CENTS_BY_ACT = {
    "ACOUSTIC_MUSIC": 12000,
    "AMPLIFIED_MUSIC": 18000,
    "STREET_THEATRE": 15000,
    "VISUAL_ART": 9000,
    "CIRCUS_SKILL": 21000,
}
ACT_TYPES = set(BASE_FEE_CENTS_BY_ACT)
AMPLIFICATION_SURCHARGE_CENTS = 6500
DISCOUNT_TIER_1_MAX_CENTS = 15000
DISCOUNT_TIER_2_MAX_CENTS = 22000
DISCOUNT_PCT = {1: Decimal("0.00"), 2: Decimal("0.10"), 3: Decimal("0.15")}
ADMIN_RATE = {1: Decimal("0.08"), 2: Decimal("0.06"), 3: Decimal("0.05")}
PRORATION_CUTOFF_MONTH = 6
SEASON_MONTHS = 12
INVOICE_DUE_DAYS = 14

TECHNICAL_WEIGHT_NUM = 3
SUITABILITY_WEIGHT_NUM = 2
SAFETY_WEIGHT_NUM = 2
WEIGHT_DENOM = 7
AUDITION_MIN_PANELISTS = 3
AUDITION_PASS_THRESHOLD = Decimal("7.00")

CONDUCT_WINDOW_DAYS = 365
STANDING_GOOD_MIN = 80
STANDING_WATCH_MIN = 60
SEVERITY_POINTS = {"MINOR": 5, "MODERATE": 12, "MAJOR": 25}
RENEWAL_MIN_CONDUCT = 80

AMPLIFIED_PENALTY_DB = 4
WARNED_PENALTY_DB = 3
ABSOLUTE_FLOOR_DB = 55
NOISE_VIOLATIONS_FOR_WARNING = 2
NOISE_VIOLATIONS_FOR_SUSPENSION = 4

SEASON_MINUTES_CAP = 1800
CHANGEOVER_BUFFER_MINUTES = 15
MIN_BOOKING_LEAD_MINUTES = 60
MAX_BOOKING_HORIZON_DAYS = 30
MAX_REVISIONS = 2

MINUTES_PER_DAY = 1440

OCCUPYING_BOOKING_STATUSES = ("RESERVED", "RELOCATED", "COMPLETED")
OCCUPYING_DRAW_STATUSES = ("OPEN", "DRAWN")


# ------------------------------------------------- permit_fee_assessment (3.4)
def fee_assessment(act_type, amplified, invoice_kind, issued_at):
    """Steps 1-6 of the fee assessment; the tier and the admin rate are both
    keyed on the PRE-discount gross."""
    gross = BASE_FEE_CENTS_BY_ACT[act_type] + (AMPLIFICATION_SURCHARGE_CENTS if amplified else 0)

    if gross <= DISCOUNT_TIER_1_MAX_CENTS:
        tier = 1
    elif gross <= DISCOUNT_TIER_2_MAX_CENTS:
        tier = 2
    else:
        tier = 3

    discount = rhu_int(Decimal(gross) * DISCOUNT_PCT[tier])
    admin = rhu_int(Decimal(gross) * ADMIN_RATE[tier])
    season_total = gross - discount + admin

    month = issued_at.month
    if invoice_kind == "RENEWAL" or month <= PRORATION_CUTOFF_MONTH:
        variant = "FULL_SEASON"
        coverage_start_month = 1
        months_covered = SEASON_MONTHS
        amount_due = season_total
    else:
        variant = "PRORATED"
        coverage_start_month = month
        months_covered = 13 - coverage_start_month
        amount_due = rhu_int(Decimal(season_total) * months_covered / Decimal(SEASON_MONTHS))

    return {
        "fee_variant": variant,
        "gross_fee_cents": gross,
        "discount_cents": discount,
        "admin_fee_cents": admin,
        "months_covered": months_covered,
        "coverage_start_month": coverage_start_month,
        "amount_due_cents": amount_due,
    }


def invoice_due_at(issued_at):
    return add_days(issued_at, INVOICE_DUE_DAYS)


# ---------------------------------------------------- revocation_refund (3.5)
def revocation_refund(invoice, refund_mode, clock):
    if refund_mode == "FULL_REFUND":
        return invoice["amount_paid_cents"]
    elapsed_months = clock.month - invoice["coverage_start_month"] + 1
    unused_months = max(0, invoice["months_covered"] - elapsed_months)
    return rhu_int(
        Decimal(invoice["amount_paid_cents"]) * unused_months / Decimal(invoice["months_covered"])
    )


# --------------------------------------------------- audition_panel_score (3.3)
def composite_score(technical, suitability, safety):
    """Per-panelist composite, rounded to 2 dp BEFORE any averaging."""
    weighted = (technical * TECHNICAL_WEIGHT_NUM
                + suitability * SUITABILITY_WEIGHT_NUM
                + safety * SAFETY_WEIGHT_NUM)
    return rhu_2dp(Decimal(weighted) / Decimal(WEIGHT_DENOM))


def panel_score(composites, score_count):
    """Mean of the ALREADY-ROUNDED composites, itself rounded to 2 dp."""
    total = sum((Decimal(str(value)) for value in composites), Decimal("0"))
    return rhu_2dp(total / Decimal(score_count))


def panel_passes(score):
    return Decimal(str(score)) >= AUDITION_PASS_THRESHOLD


# ----------------------------------------------- performer_conduct_scoring (3.8)
def age_days(clock, upheld_at):
    return int((clock - upheld_at).total_seconds() // 86400)


def conduct_scores(upheld_complaints, clock):
    """Both variants in one pass over the performer's UPHELD complaints."""
    rolling = 0
    career = 0
    for complaint in upheld_complaints:
        deduction = complaint["conduct_deduction"]
        age = age_days(clock, complaint["upheld_at"])
        if age <= CONDUCT_WINDOW_DAYS:
            rolling += deduction
            career += deduction
        else:
            career += rhu_int(Decimal(deduction) / Decimal(2))
    return max(0, 100 - rolling), max(0, 100 - career)


def standing_for(conduct_score):
    if conduct_score >= STANDING_GOOD_MIN:
        return "GOOD"
    if conduct_score >= STANDING_WATCH_MIN:
        return "WATCH"
    return "BARRED"


def upheld_deduction(severity, route):
    points = SEVERITY_POINTS[severity]
    if route == "MEDIATION":
        return rhu_int(Decimal(points) / Decimal(2))
    return points


# ------------------------------------------------- effective_noise_cap (3.1)
def effective_noise_cap(zone, pitch, amplified, compliance_status, instant):
    allowance = zone["base_noise_cap_db"]
    if is_weekend(instant):
        allowance += zone["weekend_noise_bonus_db"]
    cap = min(pitch["noise_cap_db"], allowance)
    if minute_of_day(instant) >= zone["evening_start_minute"]:
        cap -= zone["evening_penalty_db"]
    if amplified:
        cap -= AMPLIFIED_PENALTY_DB
    if compliance_status == "WARNED":
        cap -= WARNED_PENALTY_DB
    return max(cap, ABSOLUTE_FLOOR_DB)


# ------------------------------------------------------- quiet window (3.1/3.6)
def _quiet_minutes_contains(zone, minute):
    start = zone["quiet_hours_start_minute"]
    end = zone["quiet_hours_end_minute"]
    if start == end:
        return False          # no quiet window whatsoever
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end     # the window wraps midnight


def violates_quiet_window(zone, start_at, end_at):
    """True when any minute of the half-open occupation is inside the window.

    The occupation owns start_at and every instant up to but not including
    end_at, so a session that ends exactly when the quiet window opens is
    admitted.
    """
    if zone["quiet_hours_start_minute"] == zone["quiet_hours_end_minute"]:
        return False
    first_index = int(start_at.timestamp() // 60)
    last_index = int((end_at.timestamp() - 1e-6) // 60)
    span = last_index - first_index + 1
    if span <= 0:
        return False
    if span >= MINUTES_PER_DAY:
        return True
    first = minute_of_day(start_at)
    for offset in range(span):
        if _quiet_minutes_contains(zone, (first + offset) % MINUTES_PER_DAY):
            return True
    return False


# ------------------------------------------------------ pitch_slot_conflict (3.6)
def conflicts(new_start, new_end, existing_start, existing_end):
    """Half-open intervals expanded by the changeover buffer on both sides.

    Two occupations that merely touch therefore DO conflict: the buffer
    swallows the seam.
    """
    buffer = timedelta(minutes=CHANGEOVER_BUFFER_MINUTES)
    return new_start < existing_end + buffer and new_end > existing_start - buffer


# --------------------------------------------------- zone_closure_capacity (3.9)
def closures_intersect(first_start, first_end, second_start, second_end):
    """Closed intervals: orders that merely touch at an endpoint DO intersect."""
    return first_start <= second_end and first_end >= second_start


def closure_covers_booking(closure_start, closure_end, booking_start, booking_end):
    """A closed closure interval against a half-open occupation."""
    return booking_start <= closure_end and booking_end > closure_start


# --------------------------------------------------- lottery ranking keys (3.7)
def priority_band(premium_wins_this_season):
    if premium_wins_this_season == 0:
        return 1
    if premium_wins_this_season == 1:
        return 2
    return 3


def slot_duration_minutes(draw):
    return whole_minutes(draw["slot_start_at"], draw["slot_end_at"])
