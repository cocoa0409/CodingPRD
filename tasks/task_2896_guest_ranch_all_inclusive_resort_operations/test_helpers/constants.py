"""Domain thresholds and canonical test literals drawn from the PRD's calculations."""

# --- package_charge_total: length-of-stay discount bands ---
LOS_BAND_1_MAX_NIGHTS = 7
LOS_BAND_2_MAX_NIGHTS = 13
LOS_BAND_2_DISCOUNT_PCT = 0.05
LOS_BAND_3_DISCOUNT_PCT = 0.08

# --- folio_settlement_amount ---
GRATUITY_PCT = 0.18
HIGH_SPEND_THRESHOLD_CENTS = 1_200_000
HIGH_SPEND_CREDIT_BONUS_CENTS = 5_000

# --- horse_load_index / mount_selection_ranking ---
MAX_DAILY_MOUNT_HOURS = 4.0
MOUNT_RECOVERY_MINUTES = 60
MAX_CONSECUTIVE_DUTY_DAYS = 5

# --- guide_staffing_requirement ---
BEGINNER_PER_GUIDE = 4
NOVICE_PER_GUIDE = 6
INTERMEDIATE_PER_GUIDE = 8
ADVANCED_PER_GUIDE = 10
STEEP_TERRAIN_MIN_GUIDES = 2
FLAT_TERRAIN_MIN_GUIDES = 1
MINOR_PRESENT_MIN_GUIDES = 2

# --- cancellation_refund_split ---
FULL_REFUND_DAYS = 90
HALF_REFUND_DAYS = 60
QUARTER_REFUND_DAYS = 30

# --- retention_bonus vesting cliff ---
VESTING_CLIFF_NUMERATOR = 1
VESTING_CLIFF_DENOMINATOR = 2

# --- season_financial_rollup ---
CAPITAL_RESERVE_PCT = 0.25

# --- rider_ability_rank_resolution ---
ABILITY_RANKS = {
    "UNASSESSED": 0,
    "BEGINNER": 1,
    "NOVICE": 2,
    "INTERMEDIATE": 3,
    "ADVANCED": 4,
}
RE_EVALUATION_CAP = "NOVICE"
RESTRICTED_CAP = "BEGINNER"

# --- guest_waiver_status_resolution ---
WAIVER_VALID_DAYS = 365
ADULT_AGE_YEARS = 18

# --- guide_schedule / minor rider definitions ---
MINOR_RIDER_AGE_YEARS = 12
MAX_GUIDE_DAILY_HOURS = 10.0

# --- pagination defaults ---
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- logical clock ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "LOS_BAND_1_MAX_NIGHTS": LOS_BAND_1_MAX_NIGHTS,
    "LOS_BAND_2_MAX_NIGHTS": LOS_BAND_2_MAX_NIGHTS,
    "LOS_BAND_2_DISCOUNT_PCT": LOS_BAND_2_DISCOUNT_PCT,
    "LOS_BAND_3_DISCOUNT_PCT": LOS_BAND_3_DISCOUNT_PCT,
    "GRATUITY_PCT": GRATUITY_PCT,
    "HIGH_SPEND_THRESHOLD_CENTS": HIGH_SPEND_THRESHOLD_CENTS,
    "HIGH_SPEND_CREDIT_BONUS_CENTS": HIGH_SPEND_CREDIT_BONUS_CENTS,
    "MAX_DAILY_MOUNT_HOURS": MAX_DAILY_MOUNT_HOURS,
    "MOUNT_RECOVERY_MINUTES": MOUNT_RECOVERY_MINUTES,
    "MAX_CONSECUTIVE_DUTY_DAYS": MAX_CONSECUTIVE_DUTY_DAYS,
    "FULL_REFUND_DAYS": FULL_REFUND_DAYS,
    "HALF_REFUND_DAYS": HALF_REFUND_DAYS,
    "QUARTER_REFUND_DAYS": QUARTER_REFUND_DAYS,
    "CAPITAL_RESERVE_PCT": CAPITAL_RESERVE_PCT,
    "WAIVER_VALID_DAYS": WAIVER_VALID_DAYS,
    "ADULT_AGE_YEARS": ADULT_AGE_YEARS,
}

# --------------------------------------------------------------------------
# Canonical season / stay literals reused across the suite.
# --------------------------------------------------------------------------

SEASON_NAME = "2026 Fall Season"
SEASON_ARRIVAL_WEEKDAY = "SUNDAY"
SEASON_START_DATE = "2026-09-06"
SEASON_END_DATE = "2026-11-15"
SEASON_MIN_STAY_NIGHTS = 7
SEASON_MAX_STAY_NIGHTS = 21
SEASON_DEPOSIT_PCT = 0.30
SEASON_BUYOUT_PREMIUM_PCT = 0.15
SEASON_NO_SHOW_PENALTY_CENTS = 4500
SEASON_RETENTION_BONUS_CENTS = 120000
SEASON_DINING_SEAT_CAPACITY = 8

TIER_CLASSIC = {
    "code": "CLASSIC",
    "adult_nightly_rate_cents": 68500,
    "child_discount_pct": 0.375,
    "included_activity_credit_cents": 15000,
}
TIER_SIGNATURE = {
    "code": "SIGNATURE",
    "adult_nightly_rate_cents": 92000,
    "child_discount_pct": 0.25,
    "included_activity_credit_cents": 40000,
}

# Canonical 7-night stay window (Sunday to Sunday, inside the season).
ARRIVAL_DATE = "2026-10-11"
DEPARTURE_DATE = "2026-10-18"
PRIOR_ARRIVAL_DATE = "2026-10-04"
PRIOR_DEPARTURE_DATE = "2026-10-11"

# Canonical slot window on the day after arrival.
SLOT_DATE = "2026-10-12"
SLOT_STARTS_AT = "2026-10-12T15:00:00Z"
SLOT_ENDS_AT = "2026-10-12T17:00:00Z"

TEST_DEFAULTS = {
    "CABIN_BED_CAPACITY": 4,
    "SLOT_CAPACITY": 4,
    "RIDER_SURCHARGE_CENTS": 20000,
    "HORSE_WEIGHT_LIMIT_LB": 240,
}
