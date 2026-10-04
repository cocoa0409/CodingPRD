"""Domain thresholds and pinned constants from the pricing, timing and rotation rules."""

# --- Settlement ---------------------------------------------------------------
GUESTS_BILLED_CAP = 3
COMPLIMENT_CREDIT_CENTS = 500
CELEBRATION_FEE_CENTS = 900
CELEBRATION_TIER_MULTIPLIER = {
    "NONE": 0.0,
    "BIRTHDAY": 1.0,
    "ANNIVERSARY": 1.0,
    "GRADUATION": 1.2,
    "CORPORATE": 1.5,
}

# --- Table-minimum true-up ----------------------------------------------------
SHORTFALL_BAND_1_CENTS = 1000
SHORTFALL_BAND_2_CENTS = 2000
SHORTFALL_FACTOR_BAND_1 = 0.50
SHORTFALL_FACTOR_BAND_2 = 0.60
SHORTFALL_FACTOR_BAND_3 = 0.75
TABLE_MINIMUM_TRUEUP_ROUND_INCREMENT_CENTS = 25

# --- Seat surcharge -----------------------------------------------------------
SURCHARGE_ROUNDING_INCREMENT_CENTS = 25

# --- Credit application -------------------------------------------------------
CREDIT_CAP_CENTS = 2500
CREDIT_CAP_PCT = 0.12
CREDIT_ELIGIBLE_TIERS = ["GOLD", "PLATINUM"]
CREDIT_MIN_AMOUNT_CENTS = 500

# --- Chef rotation ------------------------------------------------------------
MIN_CHEF_RESET_MINUTES = 3
SHORT_TABLE_BONUS = 80

# --- Protein --------------------------------------------------------------
PROTEIN_COST_CENTS_PER_GRAM = 4.0
PROTEIN_GRAM_COST_CONTROL_PCT = 0.05
PROTEIN_PORTS_PER_GUEST = 1
GUEST_PORT_SHARE_DIVISOR = 4
PROTEIN_GRAM_PORT_SIZE = 30
PROTEIN_VARIANCE_CAP_GRAMS = 40

# --- Sushi / course timing ------------------------------------------------
SUSHI_ADVANCE_MINUTES = 6
GRILL_START_LEAD_MINUTES = 9
SUSHI_LEAD_DIVISOR = 3
LATE_GRILL_THRESHOLD_MINUTES = 6
LATE_EARLY_GRILL_DEBT_MINUTES = 3
LATE_EARLY_CHEF_DEBT_MINUTES = 2
SUSHI_PLATE_LATENESS_MINUTES = 8
RESTAGE_PLATE_MINUTES = 5
PLATE_DWELL_MINUTES = 5
SUSHI_COUNTER_SEAT_CAPACITY = 1
HOURLY_TRIGGER_MINUTE = 35
EARLY_GRILL_TOLERANCE_MINUTES = 10
SHOW_UNDERRUN_TOLERANCE_MINUTES = 4

# --- Turn-over / turn debt ------------------------------------------------
GRID_SNAP_MINUTES = 5
TURN_DEBT_BUCKET_WIDTH_MINUTES = 5
BURST_TURN_DEBT_FACTOR_PCT = 150
SHORTFALL_CAPACITY_MINUTES = 480
SHORTFALL_LETTER_COUNT = 20
SHORTFALL_BUCKET_MINUTES = [
    3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12,
]
MAX_TURN_DEBT_ADD_MINUTES = 20
TURN_DEBT_ESCALATION_THRESHOLD = 20

# --- Venue floor charge ---------------------------------------------------
ASSIGNMENT_FEE_CENTS = 299
ASSIGNABLE_GUEST_CAP = 12
ASSIGNMENT_FEE_MULTIPLIER = {"LOW": 0.90, "MEDIUM": 1.00, "HIGH": 1.20}
ROUNDING_INCREMENT_CENTS = 100
READY_TIER_CODES = ["T2", "T4", "T6", "T8"]

# --- Booking / hold windows -----------------------------------------------
BOOKING_HORIZON_MINUTES = 20160
HOLD_WINDOW_MINUTES = 20
HOLD_MAX_COUNT = 3
PRIOR_HOLD_GRACE_MINUTES = 30
NO_SHOW_GRACE_MINUTES = 30
NO_SHOW_RESTRICTION_COUNT = 2
MAINTENANCE_LATE_GRACE_MINUTES = 30
GRILL_REBUILD_MINUTES = 120

THRESHOLDS = {
    "GUESTS_BILLED_CAP": GUESTS_BILLED_CAP,
    "COMPLIMENT_CREDIT_CENTS": COMPLIMENT_CREDIT_CENTS,
    "CELEBRATION_FEE_CENTS": CELEBRATION_FEE_CENTS,
    "SHORTFALL_BAND_1_CENTS": SHORTFALL_BAND_1_CENTS,
    "SHORTFALL_BAND_2_CENTS": SHORTFALL_BAND_2_CENTS,
    "TABLE_MINIMUM_TRUEUP_ROUND_INCREMENT_CENTS": TABLE_MINIMUM_TRUEUP_ROUND_INCREMENT_CENTS,
    "SURCHARGE_ROUNDING_INCREMENT_CENTS": SURCHARGE_ROUNDING_INCREMENT_CENTS,
    "CREDIT_CAP_CENTS": CREDIT_CAP_CENTS,
    "CREDIT_MIN_AMOUNT_CENTS": CREDIT_MIN_AMOUNT_CENTS,
    "MIN_CHEF_RESET_MINUTES": MIN_CHEF_RESET_MINUTES,
    "SHORT_TABLE_BONUS": SHORT_TABLE_BONUS,
    "PROTEIN_COST_CENTS_PER_GRAM": PROTEIN_COST_CENTS_PER_GRAM,
    "PROTEIN_VARIANCE_CAP_GRAMS": PROTEIN_VARIANCE_CAP_GRAMS,
    "SUSHI_PLATE_LATENESS_MINUTES": SUSHI_PLATE_LATENESS_MINUTES,
    "PLATE_DWELL_MINUTES": PLATE_DWELL_MINUTES,
    "HOURLY_TRIGGER_MINUTE": HOURLY_TRIGGER_MINUTE,
    "EARLY_GRILL_TOLERANCE_MINUTES": EARLY_GRILL_TOLERANCE_MINUTES,
    "SHOW_UNDERRUN_TOLERANCE_MINUTES": SHOW_UNDERRUN_TOLERANCE_MINUTES,
    "ASSIGNMENT_FEE_CENTS": ASSIGNMENT_FEE_CENTS,
    "ASSIGNABLE_GUEST_CAP": ASSIGNABLE_GUEST_CAP,
    "ROUNDING_INCREMENT_CENTS": ROUNDING_INCREMENT_CENTS,
    "BOOKING_HORIZON_MINUTES": BOOKING_HORIZON_MINUTES,
    "HOLD_WINDOW_MINUTES": HOLD_WINDOW_MINUTES,
    "HOLD_MAX_COUNT": HOLD_MAX_COUNT,
    "MAINTENANCE_LATE_GRACE_MINUTES": MAINTENANCE_LATE_GRACE_MINUTES,
    "GRILL_REBUILD_MINUTES": GRILL_REBUILD_MINUTES,
}

# --- Test-side defaults ---------------------------------------------------
TEST_DEFAULTS = {
    "VENUE_NAME": "Midtown Iron Grill",
    "CITY_CODE": "NYC",
    "VENTILATION_ZONE": "ZONE_A",
    "FILTER_SERVICE_THRESHOLD_INDEX": 40,
    "BASE_RATE_PER_GUEST_CENTS": 3200,
    "PROTEIN_GRAM_STANDARD": 240,
    "SCHEDULED_TIME": "2026-09-03T19:00:00Z",
    "CLOCK_DEFAULT": "2026-09-02T12:00:00Z",
    "SERVICE_DATE": "2026-09-03",
    "PAYMENT_MODE": "CARD_ONLY",
}

# Convenience aliases used widely by the fixtures.
TIER_ROWS = {
    "T2": {
        "tier_code": "T2", "over_capacity_ratio": 1.25, "seat_capacity": 2,
        "base_rate_per_guest_cents": 3200, "minimum_bill_cents": 8000,
        "protein_gram_standard": 240, "chef_show_minutes": 40,
        "turn_time_standard_minutes": 50, "turn_time_celebration_minutes": 70,
    },
    "T4": {
        "tier_code": "T4", "over_capacity_ratio": 1.25, "seat_capacity": 4,
        "base_rate_per_guest_cents": 3200, "minimum_bill_cents": 14000,
        "protein_gram_standard": 240, "chef_show_minutes": 45,
        "turn_time_standard_minutes": 60, "turn_time_celebration_minutes": 80,
    },
    "T6": {
        "tier_code": "T6", "over_capacity_ratio": 1.25, "seat_capacity": 6,
        "base_rate_per_guest_cents": 3200, "minimum_bill_cents": 16000,
        "protein_gram_standard": 240, "chef_show_minutes": 50,
        "turn_time_standard_minutes": 75, "turn_time_celebration_minutes": 95,
    },
}