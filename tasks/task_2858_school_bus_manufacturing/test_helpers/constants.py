"""Domain thresholds and numeric constants stated by the PRD."""

# ---------------------------------------------------------------- logical clock
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ------------------------------------------------------------------- pagination
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# -------------------------------------------------------------- range modelling
TERRAIN_FACTORS = {
    "FLAT": 1.00,
    "ROLLING": 1.08,
    "MOUNTAIN": 1.18,
}

# The HVAC term is spread over a twenty-mile-per-hour average duty cycle.
HVAC_DUTY_CYCLE_MPH = 20.0

# ---------------------------------------------------------------- unit pricing
PRICING = {
    "SEAT_UPCHARGE_CENTS": 34_500,
    "EIGHT_LAMP_CENTS": 148_000,
    "CROSSING_ARM_CENTS": 96_500,
    "MIRROR_STANDARD_CENTS": 0,
    "MIRROR_CROSSVIEW_CENTS": 57_400,
    "MIRROR_CROSSVIEW_HEATED_CENTS": 83_275,
    "BELT_PER_SEAT_CENTS": 21_750,
    "EXTRA_EXIT_CENTS": 68_000,
    "ROLLOVER_REINFORCEMENT_CENTS": 213_000,
    "PREP_FEE_RATE": 0.02375,
}

# Rollover reinforcement adds this much to the body's joint strength.
ROLLOVER_JOINT_STRENGTH_BONUS_KN = 9.5

# --------------------------------------------------------------- award pricing
AWARD_PRICING = {
    "ESCALATION_RATE_PER_MONTH": 0.0045,
    "ESCALATION_DAYS_PER_MONTH": 30,
    "ADMIN_FEE_RATE": 0.0125,
}

VOLUME_DISCOUNT_TIERS = [
    # (minimum unit_count, discount percent)
    (1, 0.0),
    (10, 2.0),
    (25, 3.5),
    (50, 5.0),
]

FREIGHT_TIERS = {
    "UNDER_50M_CENTS": 1_250_000,
    "UNDER_150M_CENTS": 2_100_000,
    "AT_OR_OVER_150M_CENTS": 2_950_000,
    "FIRST_BREAK_CENTS": 50_000_000,
    "SECOND_BREAK_CENTS": 150_000_000,
}

# ------------------------------------------------------------- plant scheduling
SCHEDULING = {
    "SLOT_DEADLINE_LEAD_DAYS": 21,
    "AT_RISK_WINDOW_DAYS": 45,
}

# ---------------------------------------------------------- liquidated damages
DAMAGES = {
    "PER_UNIT_PER_DAY_CENTS": 7_500,
    "CAP_RATE_OF_TOTAL": 0.05,
}

# ----------------------------------------------------------------- test minima
ROLLOVER_MIN_VALUE_PER_LB = 0.0025

ALWAYS_REQUIRED_TEST_TYPES = ["BRAKE", "EMERGENCY_EXIT", "ELECTRICAL"]
SAFETY_CRITICAL_TEST_TYPES = ["BRAKE", "ROLLOVER"]

# ------------------------------------------------------------- dealer standing
DEALER_STANDING_THRESHOLDS = {
    "RESTRICTED_AT": 2,
    "SUSPENDED_AT": 4,
}

# --------------------------------------------------------------- bid revisions
MAX_REVISION_ROUNDS = 3
