"""Domain thresholds and pinned constants from the PRD's calculation rules.

Every value here is re-derived from PRD prose (§2.5, §3.1-§3.10), not copied
blindly from any worked example: the derivation is noted beside each entry so a
reader can check it against the contract.
"""

# --- Programming fee schedule (PRD §3.2) -------------------------------------
SCHEDULE_DEFAULTS = {
    "fiscal_year": 2026,
    "base_fee_cents": 1200000,
    "revenue_rate_bps": 250,
    "market_tier_1_max_rank": 25,
    "market_tier_2_max_rank": 75,
    "market_tier_3_max_rank": 150,
    "market_size_multiplier_bps": 12500,
    "minimum_fee_cents": 100000,
    "maximum_fee_cents": 5000000,
    "annual_adjustment_bps": 0,
    "rounding_mode": "ROUND_PER_COMPONENT_THEN_SUM",
    "effective_from": "2026-06-01T00:00:00Z",
    "effective_to": "2027-06-01T00:00:00Z",
}

# PRD §3.2: tiers 2, 3 and 4 use a pinned ladder, never the schedule's own figure.
MARKET_TIER_MULTIPLIER_BPS = {2: 14000, 3: 15500, 4: 16500}

# PRD §3.2: the class multiplier scales the market component only.
MEMBERSHIP_CLASS_FEE_MULTIPLIER_BPS = {
    "CLASS_A": 11500,
    "CLASS_B": 10000,
    "CLASS_C": 8750,
    "CLASS_D": 7500,
}

# --- Station operations score and class ladder (PRD §3.1) --------------------
WEIGHT_COVERAGE = 0.40
WEIGHT_STAFFING = 0.35
WEIGHT_NEWSROOM = 0.25
COVERAGE_INDEX_STEP_PERSONS = 100000
COVERAGE_INDEX_PER_STEP = 9
STAFFING_INDEX_PER_FTE = 5
NEWSROOM_INDEX_PER_FTE = 10
INDEX_CAP = 100

HOUSEHOLD_INDEX_STEP = 50000
HOUSEHOLD_INDEX_PER_STEP = 5
HOUSEHOLD_INDEX_CAP = 100

CLASS_A_SCORE_MIN = 75.00
CLASS_A_HOUSEHOLD_INDEX_MIN = 45
CLASS_B_SCORE_MIN = 60.00
CLASS_B_HOUSEHOLD_INDEX_MIN = 30
CLASS_C_SCORE_MIN = 45.00
CLASS_C_HOUSEHOLD_INDEX_MIN = 15

# PRD §3.1: eligibility floors and the probation restore floor.
ELIGIBILITY_COVERAGE_FLOOR = 50000
ELIGIBILITY_STAFF_FLOOR = 3
ELIGIBILITY_NEWSROOM_FLOOR = 2
PROBATION_RESTORE_SCORE_FLOOR = 55.00

# --- Carriage exceptions (PRD §3.5) ------------------------------------------
REJECTED_BASE_CENTS = 25000
VIOLATED_BASE_CENTS = 75000
UNFILLED_SLOT_BASE_CENTS = 40000
COVERAGE_BREACH_BPS_PER_MINUTE = 100
COVERAGE_BREACH_CAP_BPS = 10000
CLEARED_WHEN_EMPTY_BPS = 10000

# --- Content compensation (PRD §3.6) -----------------------------------------
BASE_CREDIT_CENTS = 50000
NOMINAL_DURATION_SECONDS = 180
CONTRIBUTING_CLASS_FACTOR_BPS = {
    "CLASS_A": 10000,
    "CLASS_B": 9500,
    "CLASS_C": 8500,
    "CLASS_D": 8000,
}
REVISION_MULTIPLIER_STEP_BPS = 500
MIN_REVISION_MULTIPLIER_BPS = 5000
CONFERENCE_RATE_CENTS = 60000
DURATION_FACTOR_CAP_BPS = 20000
CREDIT_CAP_CENTS = 250000

# --- Drive dues deduction (PRD §3.7) -----------------------------------------
DUES_ROUNDING_HEADROOM_CENTS = 500000
DRIVE_SETTLE_COLLECTION_FLOOR_BPS = 6000

# --- Acknowledgment language rule (PRD §3.8) ---------------------------------
FORBIDDEN_PHRASES = [
    "best", "cheapest", "lowest price", "guarantee", "free", "sale",
    "bestseller", "recommend",
]
COMPARATIVE_TOKENS = ["better than", "outperforms", "cheaper than"]
CALL_TO_ACTION_TOKENS = ["call now", "visit today", "buy"]
MAX_ACK_WORDS = 30
VIOLATION_ORDER = [
    "SUPERLATIVE", "COMPARATIVE", "PRICE_INVITATION", "CALL_TO_ACTION", "LENGTH",
]

# --- Dues pool allocation (PRD §3.9) -----------------------------------------
STATION_TIER_SHARE_CENTS = 120000
WATERFALL_TIER_ORDER = ["CLASS_A", "CLASS_B", "CLASS_C", "CLASS_D"]

# --- Weighted voting (PRD §3.9) ----------------------------------------------
MEMBERSHIP_CLASS_VOTE_WEIGHT = {
    "CLASS_A": 3, "CLASS_B": 2, "CLASS_C": 1, "CLASS_D": 0,
}
DEFAULT_NETWORK_RATE_BPS = 250

# --- Standings / cost-efficiency match (PRD §3.10) ---------------------------
MATCH_BUDGET_PER_STATION_CENTS = 450000
EFFICIENCY_FLOOR_BPS = 8000

# --- Misc domain constants ---------------------------------------------------
CAPACITY_UNITS_PER_SLOT = 1

# PRD §2.5: "Basis-point quantities are likewise integers, where 10000 basis
# points is one whole unit of the thing being measured — a rate, a multiplier,
# a ratio or a percentage expressed at four decimal places. No monetary or
# basis-point field is ever transmitted or stored as a decimal fraction."
# PRD §3.4: `crowded` is true when reserved/total has reached
# `max_reserved_capacity_ratio`; a congestion threshold of four fifths is
# therefore the integer 8000 basis points, not the decimal fraction 0.8.
DEFAULT_MAX_RESERVED_CAPACITY_RATIO_BPS = 8000
RATIO_SCALE_BPS = 10000

# PRD §3.4: "a lower number is the higher priority"; the displacement is
# strictly greater-than against the floor, so priorities above 3 lose while 3
# and below survive. PRD §3.4 does not name the floor's value, but the rule's
# own worked figures pin it at 3: "The priority_rank 4 slot moves to PREEMPTED
# because 4 is above the floor of 3" while "The priority_rank 3 slot stays
# SCHEDULED, so the floor comparison is strictly greater-than".
DEFAULT_PREEMPTIBLE_PRIORITY_RANK_FLOOR = 3

# Default logical clock instant (PRD §2.8).
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def coverage_index(coverage_population: int) -> int:
    """PRD §3.1: nine points per whole hundred-thousand persons begun, capped 100."""
    return min(INDEX_CAP, (coverage_population // COVERAGE_INDEX_STEP_PERSONS) * COVERAGE_INDEX_PER_STEP)


def staffing_index(full_time_staff_count: int) -> int:
    """PRD §3.1: five points per full-time staff member, capped 100."""
    return min(INDEX_CAP, full_time_staff_count * STAFFING_INDEX_PER_FTE)


def newsroom_index(newsroom_staff_count: int) -> int:
    """PRD §3.1: ten points per full-time newsroom staff member, capped 100."""
    return min(INDEX_CAP, newsroom_staff_count * NEWSROOM_INDEX_PER_FTE)


def households_index(dma_households: int) -> int:
    """PRD §3.1: five points per fifty-thousand households begun, capped 100."""
    return min(HOUSEHOLD_INDEX_CAP, (dma_households // HOUSEHOLD_INDEX_STEP) * HOUSEHOLD_INDEX_PER_STEP)


def operations_score(coverage_population: int, full_time_staff_count: int,
                     newsroom_staff_count: int) -> float:
    """PRD §3.1: weighted sum of the three individually capped indices."""
    return round(
        WEIGHT_COVERAGE * coverage_index(coverage_population)
        + WEIGHT_STAFFING * staffing_index(full_time_staff_count)
        + WEIGHT_NEWSROOM * newsroom_index(newsroom_staff_count),
        2,
    )


def membership_class_for(score: float, dma_households: int) -> str:
    """PRD §3.1: the first ladder gate whose condition pair both hold wins."""
    idx = households_index(dma_households)
    if score >= CLASS_A_SCORE_MIN and idx >= CLASS_A_HOUSEHOLD_INDEX_MIN:
        return "CLASS_A"
    if score >= CLASS_B_SCORE_MIN and idx >= CLASS_B_HOUSEHOLD_INDEX_MIN:
        return "CLASS_B"
    if score >= CLASS_C_SCORE_MIN and idx >= CLASS_C_HOUSEHOLD_INDEX_MIN:
        return "CLASS_C"
    return "CLASS_D"


def yes_vote_weight(membership_class: str) -> int:
    """PRD §3.9: a YES records the station's class base weight."""
    return MEMBERSHIP_CLASS_VOTE_WEIGHT[membership_class]


def no_vote_weight(membership_class: str) -> int:
    """PRD §3.9: a NO records (base + 1) // 2 with a floor of 1, zero when base is 0."""
    base = MEMBERSHIP_CLASS_VOTE_WEIGHT[membership_class]
    if base <= 0:
        return 0
    return max(1, (base + 1) // 2)


def mature_dues_cents(provisional_fee_cents: int) -> int:
    """PRD §3.7: the deduction ceiling is the provisional fee less the headroom."""
    return provisional_fee_cents - DUES_ROUNDING_HEADROOM_CENTS


def round_half_up(value: float) -> int:
    """PRD §2.5: a fractional part of exactly one half rounds away from zero."""
    import math
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))


def duration_factor_bps(duration_seconds: int) -> int:
    """PRD §3.6: duration scaled to the nominal 180 seconds, capped at 20000 bps."""
    return min(DURATION_FACTOR_CAP_BPS,
               (duration_seconds * 10000) // NOMINAL_DURATION_SECONDS)


def shelf_credit_cents(membership_class: str, duration_seconds: int,
                       revision_count: int) -> int:
    """PRD §3.6: the working branch's credit before the published-floor selector."""
    factor = duration_factor_bps(duration_seconds)
    base = round_half_up(BASE_CREDIT_CENTS * factor / 10000)
    class_credit = round_half_up(
        base * CONTRIBUTING_CLASS_FACTOR_BPS[membership_class] / 10000)
    multiplier = max(MIN_REVISION_MULTIPLIER_BPS,
                     10000 - revision_count * REVISION_MULTIPLIER_STEP_BPS)
    return round_half_up(class_credit * multiplier / 10000)


def compensation_credit_cents(membership_class: str, duration_seconds: int,
                              revision_count: int, published: bool) -> int:
    """PRD §3.6: the shelf figure, floored at the conference rate when published."""
    shelf = shelf_credit_cents(membership_class, duration_seconds, revision_count)
    raw = max(shelf, CONFERENCE_RATE_CENTS) if published else shelf
    return min(raw, CREDIT_CAP_CENTS)


def provisional_fee_cents(schedule: dict, station: dict,
                          membership_class: str) -> int:
    """PRD §3.2: rounded rate component plus class-scaled market component, clamped.

    Each component is rounded to the cent before the sum, and the clamp is the
    final step of the pipeline.
    """
    rank = station["dma_market_rank"]
    if rank <= schedule["market_tier_1_max_rank"]:
        tier = 1
    elif rank <= schedule["market_tier_2_max_rank"]:
        tier = 2
    elif rank <= schedule["market_tier_3_max_rank"]:
        tier = 3
    else:
        tier = 4
    multiplier_bps = (schedule["market_size_multiplier_bps"] if tier == 1
                      else MARKET_TIER_MULTIPLIER_BPS[tier])
    rate_component = round_half_up(
        station["annual_local_revenue_cents"] * schedule["revenue_rate_bps"] / 10000)
    market_component = round_half_up(
        (schedule["base_fee_cents"] * multiplier_bps / 10000)
        * MEMBERSHIP_CLASS_FEE_MULTIPLIER_BPS[membership_class] / 10000)
    total = rate_component + market_component
    return min(max(total, schedule["minimum_fee_cents"]), schedule["maximum_fee_cents"])