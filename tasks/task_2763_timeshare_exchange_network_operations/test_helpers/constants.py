"""Domain constants of the Timeshare Exchange Network API.

Every figure here is stated in the PRD narrative (§2.5–§2.10, §3.1–§3.9).
"""

# ---------------------------------------------------------------- the clock
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ------------------------------------------------- week valuation (PRD §3.3)
UNIT_SIZE_BASE = {
    "STUDIO": 30,
    "ONE_BR": 45,
    "TWO_BR": 60,
    "THREE_BR": 80,
}

SEASON_MULTIPLIER = {
    "PLATINUM": "1.50",
    "GOLD": "1.25",
    "SILVER": "1.00",
    "BRONZE": "0.70",
}

QUALITY_BONUS = {
    "GOLD_CROWN": 6,
    "SILVER_CROWN": 3,
    "STANDARD": 0,
    "HOSPITALITY": -4,
}

# (threshold_days, factor) scanned from the top; catch-all last.
LEAD_TIME_FACTOR_BANDS = (
    (270, "1.20"),
    (180, "1.10"),
    (90, "1.00"),
    (None, "0.85"),
)

TRADING_POWER_FLOOR = 1

# ------------------------------------------- exchange charge bands (PRD §3.4)
SHORTFALL_CENTS_PER_POINT = 350

# (subtotal_upper_bound_inclusive, credit_pct) scanned from the top.
DEPOSIT_FIRST_CREDIT_BANDS = (
    (9999, 0),
    (19999, 5),
    (None, 10),
)

# (subtotal_upper_bound_inclusive, processing_fee_cents) scanned from the top.
PROCESSING_FEE_BANDS = (
    (14999, 1200),
    (29999, 2000),
    (None, 2900),
)

REQUEST_FIRST_BUDGET_DIVISOR = 110

# ------------------------------------------------ getaway pricing (PRD §3.7)
GETAWAY_CENTS_PER_POWER_POINT = 900
GETAWAY_DEMAND_PREMIUM_PCT_PER_STEP = 5

# (threshold_days, discount_pct) scanned from the top.
URGENCY_DISCOUNT_BANDS = (
    (120, 0),
    (60, 10),
    (30, 20),
    (None, 35),
)

GETAWAY_PRICE_FLOOR_CENTS = 29900
GETAWAY_PRICE_CEILING_CENTS = 249900

# ------------------------------------------------ quality ladder (PRD §3.8)
COMPOSITE_WEIGHTS = {
    "cleanliness_score": "0.40",
    "service_score": "0.35",
    "amenities_score": "0.25",
}

QUALITY_SCORE_BANDS = (
    ("8.50", "GOLD_CROWN"),
    ("7.00", "SILVER_CROWN"),
    ("5.00", "STANDARD"),
    (None, "HOSPITALITY"),
)

QUALITY_LADDER = ("GOLD_CROWN", "SILVER_CROWN", "STANDARD", "HOSPITALITY")
REVIEW_SCORING_WINDOW = 8
MIN_REVIEWS_FOR_SCORE = 2
MAX_DOWNGRADE_NOTCHES = 3
COMPLAINT_STRIKES_PER_NOTCH = 2

# --------------------------------------------- priority scoring (PRD §3.5)
TIER_PRIORITY_WEIGHT = {"BASIC": 0, "PLUS": 20, "ELITE": 40}
DEPOSIT_FIRST_PRIORITY_BONUS = 15
TENURE_POINTS_CAP = 10
DAYS_PER_TENURE_YEAR = 365
DECLINE_PENALTY_POINTS = 5
DUES_SHORTFALL_PENALTY_POINTS = 25

# --------------------------------------------- operational spans and caps
STAY_NIGHTS = 7
OCCUPANCY_NIGHTS_PER_DEPOSIT = 8
DEPOSIT_LIFETIME_DAYS = 730
EXTENSION_DAYS_PER_MONTH = 30
MAX_EXTENSION_MONTHS = 12
DEPOSIT_LEAD_MIN_DAYS = 60
REQUEST_WINDOW_MAX_SPAN_DAYS = 60
MATCH_HOLD_HOURS = 48
REINSTATEMENT_WINDOW_DAYS = 14
GETAWAY_SWEEP_WITHIN_DAYS = 45
MAX_DISPUTE_ROUNDS = 2
AFFILIATION_YEAR_DAYS = 365

# --------------------------------------------- cancellation (PRD §3.6)
FULL_RESTORE_MIN_DAYS_OUT = 30
RESTORATION_HAIRCUT_PCT = 25
LATE_CANCELLATION_SURCHARGE_CENTS = 7500

# --------------------------------------------- pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------- run counter field names
RUN_COUNTER_FIELDS = (
    "lapsed_member_count",
    "expired_deposit_count",
    "probation_resort_count",
    "expired_request_count",
    "denied_request_count",
    "matched_count",
    "waitlisted_count",
    "completed_confirmation_count",
    "getaway_listed_count",
)
