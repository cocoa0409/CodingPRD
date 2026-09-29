"""Pure calculation rules (PRD section 3, SCAFFOLD calculations)."""
from decimal import Decimal

from common import (
    D, ceil_div, ceil_int, one_dp, parse_date, round_half_up_int,
    round_half_up_places, whole_months_between,
)

# ------------------------------------------------------------------ constants
BASE_ENTRY_FEE_CENTS = 3500
PERFORMANCE_ENTRY_FEE_CENTS = 2800
FIRST_ENTRY_SURCHARGE_CENTS = 900
CATALOG_LEVY_PCT = Decimal("0.075")
SAME_DOG_DISCOUNT_PCT = Decimal("0.15")
HOUSEHOLD_DISCOUNT_PCT = Decimal("0.10")
HOUSEHOLD_DISCOUNT_MIN_ENTRIES = 3

REFUND_HIGH_MIN_CENTS = 20000
REFUND_HIGH_PCT = Decimal("0.10")
REFUND_MID_MIN_CENTS = 10000
REFUND_MID_PCT = Decimal("0.05")
REFUND_LOW_PCT = Decimal("0.00")

POINTS_TABLE = [
    (0, 1, 0),
    (2, 4, 1),
    (5, 9, 2),
    (10, 17, 3),
    (18, 29, 4),
    (30, None, 5),
]
MAJOR_MIN_POINTS = 2
GROUP_WIN_BONUS_POINTS = 2
BIS_BONUS_POINTS = 3
POINTS_CAP_PER_CLASS = 5
MAX_PLACEMENTS = 4

DOGS_PER_HOUR_CONFORMATION = 25
DOGS_PER_HOUR_PERFORMANCE = 15
GROUP_JUDGING_OVERHEAD_MINUTES = 10
CONFLICT_BUFFER_MINUTES_PER_DOG = 3
MINUTES_PER_HOUR = 60

RING_TURNAROUND_BUFFER_MINUTES = 0
JUDGE_REST_BUFFER_MINUTES = 30

MAX_DOGS_PER_JUDGE_PER_DAY = 175
MAX_SLOTS_PER_JUDGE_PER_SHOW = 3
MAX_SHOWS_PER_JUDGE_PER_DAY = 1

HUMIDITY_ADJUSTMENT_TABLE = [
    (40, Decimal("0.0")),
    (60, Decimal("1.5")),
    (80, Decimal("3.0")),
    (None, Decimal("5.0")),
]
ADVISORY_AMBER_MIN_C = Decimal("26.0")
ADVISORY_RED_MIN_C = Decimal("32.0")

AGILITY_BASE_SCORE = Decimal("100.0")
AGILITY_FAULT_POINTS = Decimal("5.0")
AGILITY_REFUSAL_POINTS = Decimal("5.0")
AGILITY_ELIMINATION_REFUSALS = 3
AGILITY_MAX_YARDS_PER_SECOND = Decimal("5.0")
OBEDIENCE_MAX_SCORE = Decimal("200.0")
OBEDIENCE_QUALIFYING_MIN = Decimal("170.0")
RALLY_MAX_SCORE = Decimal("100.0")
RALLY_FAULT_POINTS = Decimal("3.0")
RALLY_QUALIFYING_MIN = Decimal("70.0")

JUMP_HEIGHT_TABLE = [
    (Decimal("25"), 20),
    (Decimal("35"), 30),
    (Decimal("45"), 40),
    (Decimal("55"), 50),
    (None, 60),
]
JUMP_HEIGHTS = [20, 30, 40, 50, 60]

PROTEST_WINDOW_HOURS = 24
PROTEST_DEPOSIT_MIN_CENTS = 5000

CHAMPION_TITLE_POINTS = 3
CHAMPION_TITLE_MAJORS_REQUIRED = 1
PERFORMANCE_TITLE_LEGS_REQUIRED = 3
TITLE_CODE_ORDER = ["CH", "AX", "CD", "RN"]

MIN_ENTRY_AGE_MONTHS = 6
ENTRY_LIMIT_STATUSES = ("RECEIVED", "CONFIRMED", "CHECKED_IN", "JUDGED")
ARMBAND_FIRST_NUMBER = 1


# --------------------------------------------------------------- entry ranking
def entry_rank_key(entry):
    """created_at ASC as the sole key, ties broken by armband_number ASC."""
    armband = entry.get("armband_number")
    return (
        entry["created_at"],
        armband if armband is not None else 10 ** 9,
        entry["_seq"],
    )


# ------------------------------------------------------------ entry fee (14.1)
def base_fee_cents(class_level):
    if class_level == "PERFORMANCE":
        return PERFORMANCE_ENTRY_FEE_CENTS
    return BASE_ENTRY_FEE_CENTS


def levy_for_base(base_cents):
    return round_half_up_int(D(base_cents) * CATALOG_LEVY_PCT)


def assess_entry_fee(entry, class_level, show_entries, counted_statuses):
    """Return (entry_fee_cents, levy_cents) for one entry under one variant."""
    base_cents = base_fee_cents(class_level)
    counted = [e for e in show_entries if e["entry_status"] in counted_statuses]
    own_key = entry_rank_key(entry)

    handler_counted = [e for e in counted if e["handler_id"] == entry["handler_id"]]
    handler_rank = 1 + len(
        [e for e in handler_counted if entry_rank_key(e) < own_key]
    )
    same_dog_counted = [e for e in counted if e["dog_id"] == entry["dog_id"]]
    same_dog_rank = 1 + len(
        [e for e in same_dog_counted if entry_rank_key(e) < own_key]
    )

    surcharge = FIRST_ENTRY_SURCHARGE_CENTS if handler_rank == 1 else 0
    levy_cents = levy_for_base(base_cents)
    gross_cents = base_cents + surcharge + levy_cents

    discount_pct = Decimal("0.00")
    if same_dog_rank >= 2:
        discount_pct += SAME_DOG_DISCOUNT_PCT
    if len(handler_counted) >= HOUSEHOLD_DISCOUNT_MIN_ENTRIES:
        discount_pct += HOUSEHOLD_DISCOUNT_PCT

    fee_cents = round_half_up_int(D(gross_cents) * (Decimal(1) - discount_pct))
    return fee_cents, levy_cents


# ------------------------------------------------------------- refund (14.3)
def retention_pct_for(tier_basis_cents):
    if tier_basis_cents >= REFUND_HIGH_MIN_CENTS:
        return REFUND_HIGH_PCT
    if tier_basis_cents >= REFUND_MID_MIN_CENTS:
        return REFUND_MID_PCT
    return REFUND_LOW_PCT


def refund_split(refund_gross_cents, tier_basis_cents):
    pct = retention_pct_for(tier_basis_cents)
    retention = round_half_up_int(D(refund_gross_cents) * pct)
    return retention, refund_gross_cents - retention


# ------------------------------------------------------------- points (14.4)
def tier_points_for(counted_dog_count):
    for low, high, points in POINTS_TABLE:
        if counted_dog_count >= low and (high is None or counted_dog_count <= high):
            return points
    return 0


def counted_statuses_for_scale(effective_scale):
    if effective_scale == "SCALE_B":
        return ("CHECKED_IN", "JUDGED")
    return ("CONFIRMED", "CHECKED_IN", "JUDGED", "ABSENT")


def winner_points_for(class_level, counted_dog_count, feeder_max):
    tier = tier_points_for(counted_dog_count)
    if class_level in ("BREED", "PERFORMANCE"):
        return tier
    bonus = GROUP_WIN_BONUS_POINTS if class_level == "GROUP" else BIS_BONUS_POINTS
    return min(POINTS_CAP_PER_CLASS, feeder_max + bonus)


# ---------------------------------------------------- ring geometry (14.5/14.7)
def block_minutes(class_level, scheduled_dog_count, deferred_dog_count):
    rate = (
        DOGS_PER_HOUR_PERFORMANCE
        if class_level == "PERFORMANCE"
        else DOGS_PER_HOUR_CONFORMATION
    )
    base_minutes = ceil_div(scheduled_dog_count * MINUTES_PER_HOUR, rate)
    overhead = (
        GROUP_JUDGING_OVERHEAD_MINUTES
        if class_level in ("GROUP", "BEST_IN_SHOW")
        else 0
    )
    conflict_free = base_minutes + overhead
    estimate = conflict_free + deferred_dog_count * CONFLICT_BUFFER_MINUTES_PER_DOG
    return conflict_free, estimate


# ------------------------------------------------------------ heat index (14.9)
def humidity_adjustment(relative_humidity_pct):
    for ceiling, adjustment in HUMIDITY_ADJUSTMENT_TABLE:
        if ceiling is None or D(relative_humidity_pct) <= D(ceiling):
            return adjustment
    return Decimal("5.0")


def heat_evaluation(recorded_temp_c, relative_humidity_pct):
    adjustment = humidity_adjustment(relative_humidity_pct)
    index = round_half_up_places(D(recorded_temp_c) + adjustment, 1)
    if index >= ADVISORY_RED_MIN_C:
        level = "RED"
    elif index >= ADVISORY_AMBER_MIN_C:
        level = "AMBER"
    else:
        level = "GREEN"
    return float(index), level


# ------------------------------------------------------- run scoring (14.10)
def agility_min_standard_time(course_yardage_m):
    return ceil_int(D(course_yardage_m) / AGILITY_MAX_YARDS_PER_SECOND)


def score_run(discipline, faults_count, refusals_count, obedience_deductions,
              actual_time_s, standard_course_time_s):
    time_faults = max(0, ceil_int(D(actual_time_s) - D(standard_course_time_s)))
    if discipline == "AGILITY":
        total = (
            D(faults_count) * AGILITY_FAULT_POINTS
            + D(refusals_count) * AGILITY_REFUSAL_POINTS
            + D(time_faults)
        )
        score = max(Decimal("0.0"), AGILITY_BASE_SCORE - total)
        if refusals_count >= AGILITY_ELIMINATION_REFUSALS:
            result = "ELIMINATED"
        elif total == 0:
            result = "QUALIFIED"
        else:
            result = "NQ"
    elif discipline == "OBEDIENCE":
        total = D(obedience_deductions)
        score = OBEDIENCE_MAX_SCORE - D(obedience_deductions)
        result = "QUALIFIED" if score >= OBEDIENCE_QUALIFYING_MIN else "NQ"
    else:
        total = (
            D(obedience_deductions)
            + D(faults_count) * RALLY_FAULT_POINTS
            + D(time_faults)
        )
        score = max(Decimal("0.0"), RALLY_MAX_SCORE - total)
        result = "QUALIFIED" if score >= RALLY_QUALIFYING_MIN else "NQ"
    return {
        "time_faults": one_dp(time_faults),
        "total_faults": one_dp(total),
        "final_score": one_dp(score),
        "run_result": result,
        "title_leg_awarded": result == "QUALIFIED",
    }


# ------------------------------------------------------- jump ladder (14.11)
def eligible_jump_height(measured_height_cm):
    if measured_height_cm is None:
        return None
    for ceiling, height in JUMP_HEIGHT_TABLE:
        if ceiling is None or D(measured_height_cm) <= ceiling:
            return height
    return 60


# ------------------------------------------------------------- titles (14.13)
def earned_title_codes(dog):
    earned = set()
    if (
        dog["championship_points_total"] >= CHAMPION_TITLE_POINTS
        and dog["majors_count"] >= CHAMPION_TITLE_MAJORS_REQUIRED
    ):
        earned.add("CH")
    legs = dog.get("qualifying_leg_counts") or {}
    if legs.get("AGILITY", 0) >= PERFORMANCE_TITLE_LEGS_REQUIRED:
        earned.add("AX")
    if legs.get("OBEDIENCE", 0) >= PERFORMANCE_TITLE_LEGS_REQUIRED:
        earned.add("CD")
    if legs.get("RALLY", 0) >= PERFORMANCE_TITLE_LEGS_REQUIRED:
        earned.add("RN")
    return earned


def dog_age_months(dog, show_date):
    """Whole months from the dog's birth_date to the show's show_date."""
    return whole_months_between(parse_date(dog["birth_date"]), parse_date(show_date))
