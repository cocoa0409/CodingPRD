"""Numeric precision helpers and the ten calculation rules of PRD section 3."""

import datetime
import math
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

import store

TWO = Decimal("0.01")
ONE = Decimal("0.1")

# deficiency_points_deducted
SEVERITY_MULT = {
    "LIFE_THREATENING": Decimal("3.0"),
    "SEVERE": Decimal("2.0"),
    "MODERATE": Decimal("1.0"),
    "LOW": Decimal("0.5"),
}
AREA_MULT = {
    "UNIT": Decimal("1.0"),
    "INSIDE": Decimal("0.8"),
    "OUTSIDE": Decimal("0.6"),
}
RECURRENCE_MULT = Decimal("1.5")
OCCUPIED_LIFE_THREATENING_MULT = Decimal("1.2")
DEFICIENCY_POINT_CAP = Decimal("40.00")

# unit_sample_size
TIER_1_MAX_UNITS = 4
TIER_2_MAX_UNITS = 30
TIER_2_RATE = Decimal("0.20")
TIER_2_FLOOR = 5
TIER_3_MAX_UNITS = 100
TIER_3_RATE = Decimal("0.15")
TIER_3_FLOOR = 8
TIER_4_RATE = Decimal("0.10")
TIER_4_FLOOR = 15
TIER_4_CAP = 35

# inspection_score
REFUSAL_PENALTY_POINTS = Decimal("12.00")

# property_readiness_posture
WATCH_SEVERE_FLOOR = 5
WATCH_SCORE_FLOOR = Decimal("60.00")

# sweep_closure_verified_rate
SWEEP_CLOSURE_RATE_FLOOR = Decimal("90.00")

# cap_window_and_followup_schedule
APPEAL_WINDOW_HOURS = 360
CAP_SCORE_THRESHOLD = Decimal("90.00")
CAP_TIER_90_DAYS = 60
CAP_TIER_80_DAYS = 45
CAP_TIER_60_DAYS = 30
CAP_TIER_LOW_DAYS = 15
FOLLOWUP_OFFSET_DAYS = 30
FOLLOWUP_OFFSET_LT_DAYS = 10

# capital needs
RECURRENCE_INSPECTION_WINDOW = 2
RECURRENCE_CALENDAR_DAYS = 730
RECURRENCE_MIN_COUNT = 2
PRIORITY_SCORE_CAP = Decimal("100.00")

# notices, buffers and limits
NOTICE_LEAD_HOURS_MIN = Decimal("48.00")
INSPECTION_COOLDOWN_BUFFER_HOURS = 72
SWEEP_OVERLAP_CAPACITY = 2
URGENT_DUE_PULL_IN_HOURS = 24
APPEAL_RESUBMIT_LIMIT = 2
HUNDRED = Decimal("100.00")


def d(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return d(value).quantize(TWO, rounding=ROUND_HALF_UP)


def r1(value):
    return d(value).quantize(ONE, rounding=ROUND_HALF_UP)


def ceil_exact(value):
    return int(d(value).to_integral_value(rounding=ROUND_CEILING))


def hours(count):
    return datetime.timedelta(hours=count)


def days(count):
    return datetime.timedelta(days=count)


# --- unit_sample_size ------------------------------------------------------
def sample_tier_value(declared_unit_count):
    n = declared_unit_count
    if n <= TIER_1_MAX_UNITS:
        return n
    if n <= TIER_2_MAX_UNITS:
        return max(TIER_2_FLOOR, ceil_exact(TIER_2_RATE * n))
    if n <= TIER_3_MAX_UNITS:
        return max(TIER_3_FLOOR, ceil_exact(TIER_3_RATE * n))
    return min(TIER_4_CAP, max(TIER_4_FLOOR, ceil_exact(TIER_4_RATE * n)))


def rank_candidates(candidates):
    """prior_deficiency_count DESC, then created_at ASC. `id` is never read."""
    return sorted(candidates, key=lambda u: (-u["prior_deficiency_count"], u["_seq"]))


# --- deficiency_points_deducted -------------------------------------------
def deficiency_points(definition, inspectable_area, supersedes_deficiency_id, unit):
    severity_mult = SEVERITY_MULT[definition["severity"]]
    area_mult = AREA_MULT[inspectable_area]
    recurrence_mult = RECURRENCE_MULT if supersedes_deficiency_id else Decimal("1.0")
    occupancy_mult = Decimal("1.0")
    if (
        definition["severity"] == "LIFE_THREATENING"
        and unit is not None
        and unit["occupancy_status"] == "OCCUPIED"
    ):
        occupancy_mult = OCCUPIED_LIFE_THREATENING_MULT
    raw = (
        d(definition["base_point_value"])
        * severity_mult
        * area_mult
        * recurrence_mult
        * occupancy_mult
    )
    return min(DEFICIENCY_POINT_CAP, r2(raw))


# --- sweep_closure_verified_rate ------------------------------------------
def closure_verified_rate(work_orders):
    live = [w for w in work_orders if w["repair_status"] != "VOID"]
    denominator = len(live)
    if denominator == 0:
        return Decimal("100.00")
    numerator = len([w for w in live if w["verification_status"] == "VERIFIED"])
    return r2(d(numerator) * Decimal("100") / d(denominator))


# --- notice_lead_hours -----------------------------------------------------
def notice_lead_hours(scheduled_start, notified_at):
    delta = scheduled_start - notified_at
    seconds = (
        d(delta.days) * Decimal("86400")
        + d(delta.seconds)
        + d(delta.microseconds) / Decimal("1000000")
    )
    return r2(seconds / Decimal("3600"))


# --- inspection_score -----------------------------------------------------
def area_raw_sums(deficiency_rows):
    sums = {"UNIT": Decimal("0.00"), "INSIDE": Decimal("0.00"), "OUTSIDE": Decimal("0.00")}
    for row in deficiency_rows:
        if row["status"] == "VOIDED":
            continue
        sums[row["inspectable_area"]] = sums[row["inspectable_area"]] + d(
            row["points_deducted"]
        )
    return sums


def composite_score(sums, standard, variant, inspected_unit_count, refused_unit_count,
                    sample_size):
    unit_raw = sums["UNIT"]
    inside_raw = sums["INSIDE"]
    outside_raw = sums["OUTSIDE"]

    if variant == "PROVISIONAL":
        if inspected_unit_count > 0:
            unit_per_unit = r2(unit_raw / d(inspected_unit_count))
        else:
            unit_per_unit = Decimal("0.00")
    else:
        if sample_size > 0:
            numerator = unit_raw + REFUSAL_PENALTY_POINTS * d(refused_unit_count)
            unit_per_unit = r2(numerator / d(sample_size))
        else:
            unit_per_unit = Decimal("0.00")

    unit_area_score = r2(max(Decimal("0.00"), HUNDRED - unit_per_unit))
    inside_area_score = r2(max(Decimal("0.00"), HUNDRED - inside_raw))
    outside_area_score = r2(max(Decimal("0.00"), HUNDRED - outside_raw))

    w_unit = r2(unit_area_score * (d(standard["unit_weight_pct"]) / Decimal("100")))
    w_inside = r2(inside_area_score * (d(standard["inside_weight_pct"]) / Decimal("100")))
    w_outside = r2(outside_area_score * (d(standard["outside_weight_pct"]) / Decimal("100")))
    return r1(w_unit + w_inside + w_outside)


# --- cap_window_and_followup_schedule -------------------------------------
def cap_window_days(final_score):
    score = d(final_score)
    if score >= Decimal("90.00"):
        return CAP_TIER_90_DAYS
    if score >= Decimal("80.00"):
        return CAP_TIER_80_DAYS
    if score >= Decimal("60.00"):
        return CAP_TIER_60_DAYS
    return CAP_TIER_LOW_DAYS


# --- capital_need_priority_score ------------------------------------------
def priority_score(recurrence_count, definition):
    raw = (
        d(recurrence_count)
        * d(definition["base_point_value"])
        * SEVERITY_MULT[definition["severity"]]
    )
    return min(PRIORITY_SCORE_CAP, r2(raw))


# --- capital_reserve_allocation -------------------------------------------
def allocate_reserve(reserve_cents, ordered_priority_scores):
    """floor-then-remainder distribution; the sum equals reserve_cents exactly."""
    count = len(ordered_priority_scores)
    if count == 0:
        return []
    scaled = [int((d(p) * Decimal("100")).to_integral_value()) for p in ordered_priority_scores]
    total = sum(scaled)
    if total == 0:
        return [0] * count
    shares = [(reserve_cents * s) // total for s in scaled]
    remainder = reserve_cents - sum(shares)
    index = 0
    while remainder > 0:
        shares[index % count] = shares[index % count] + 1
        remainder -= 1
        index += 1
    return shares


# --- interval helpers -----------------------------------------------------
def closed_intervals_conflict(a_start, a_end, b_start, b_end):
    """Closed-interval intersection: touching endpoints DO conflict."""
    return a_start <= b_end and b_start <= a_end


def half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection: touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


def parse(text):
    return store.parse_instant(text)


def add_hours(instant_text, hour_count):
    """Returns a formatted instant advanced from a stored instant string."""
    base = store.parse_instant(instant_text)
    return store.fmt_instant(base + hours(hour_count))


def floor_div(a, b):
    return int(math.floor(a / b))
