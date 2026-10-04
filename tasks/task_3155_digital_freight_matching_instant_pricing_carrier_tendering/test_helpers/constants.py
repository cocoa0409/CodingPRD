"""Domain thresholds and table constants named by the PRD."""

# ------------------------------------------------------------------ clock
CLOCK_START = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------- pricing
MIN_MILES = 50
MIN_RATE_FLOOR_CENTS = 50000
MIN_RATE_FLOOR_MULTIPLE = 0.85

LANE_INDEX_MODULUS = 11
LANE_INDEX_STEP = 20

MARKET_LEVEL_CENTS_PER_MILE = {
    "DRY_VAN": {"OPEN": 210, "BALANCED": 235, "TIGHT": 275},
    "REEFER": {"OPEN": 250, "BALANCED": 285, "TIGHT": 330},
    "FLATBED": {"OPEN": 230, "BALANCED": 260, "TIGHT": 305},
}

TIMING_BAND_MULTIPLE = {
    "00:00-05:59": 0.95,
    "06:00-14:59": 1.10,
    "15:00-21:59": 1.00,
    "22:00-23:59": 1.05,
}

WEIGHT_ADJUSTMENT = {
    "DRY_VAN": {"THRESHOLD_LBS": 40000, "MULTIPLE_ABOVE": 0.02},
    "REEFER": {"THRESHOLD_LBS": 40000, "MULTIPLE_ABOVE": 0.03},
    "FLATBED": {"THRESHOLD_LBS": None, "MULTIPLE_ABOVE": 0.00},
}

COMMODITY_MULTIPLE = {
    "GENERAL": 1.00,
    "TEMPERATURE_CONTROLLED": 1.15,
    "HAZMAT": 1.25,
    "HIGH_VALUE": 1.20,
}

LOCK_WINDOW_MINUTES = 60
LATE_BOOKING_SURCHARGE_PCT = 0.05
QUOTE_TTL_HOURS = 24

# ------------------------------------------------------------------- risk
RISK_BREACH_PENALTY = 8
RISK_CLAIM_PENALTY = 12
RISK_CLAWBACK_PENALTY = 5
RISK_FLOOR = 0
RISK_CEILING = 100
RISK_ELIGIBILITY_FLOOR = 40.0
RISK_SLACK_MINUTES_PER_POINT = 2.4

# ---------------------------------------------------- carrier compliance
SAFETY_SCORE_MAX = 80.0
MIN_INSURANCE_LIABILITY_CENTS = 75000000
MIN_CARGO_COVERAGE_CENTS = 100000000

# -------------------------------------------------------------- detention
MINUTES_PER_HOUR = 60
DEFAULT_FREE_DWELL_MINUTES = 120
DEFAULT_APPOINTMENT_MINUTES = 60

# ------------------------------------------------------------- scheduling
DOCK_BUFFER_MINUTES = 120
MISSED_GRACE_MINUTES = 60
COVERAGE_HORIZON_HOURS = 24
MAX_REPOSTS = 3
MIN_WEIGHT_LBS = 1

# ----------------------------------------------------------------- claims
PRICE_CAP_MULTIPLIER = 1.5
COMMODITY_LIABILITY_CAP = {
    "GENERAL": 100000000,
    "TEMPERATURE_CONTROLLED": 100000000,
    "HAZMAT": 100000000,
    "HIGH_VALUE": 250000000,
}
TRUCKLOAD_WEIGHT_LBS = 44000
MAX_REVIEW_ROUNDS = 3
ESCALATION_THRESHOLD_CENTS = 2500000

# -------------------------------------------------- tracking and breaches
TOLERANCE_MINUTES = 30

# ------------------------------------------------------------- settlement
QUICK_PAY_TIER_RATE = {
    "0-4": 0.0300,
    "5-19": 0.0250,
    "20-49": 0.0200,
    "50+": 0.0150,
}

# --------------------------------------------------------------- defaults
TEST_DEFAULTS = {
    "SHIPPER_NAME": "Gulf Fabricators LLC",
    "SHIPPER_STATE": "TX",
    "PAYMENT_TERMS_DAYS": 30,
    "QUICK_PAY_DISCOUNT_PCT": 0.03,
    "CREDIT_LIMIT_CENTS": 20000000,
    "LOAD_CREDIT_LIMIT": 10,
    "ORIGIN_FACILITY_NAME": "Gulf Fabricators Houston",
    "DESTINATION_FACILITY_NAME": "Inland Empire DC",
    "DOCK_CAPACITY": 3,
    "DETENTION_RATE_PER_HOUR_CENTS": 7500,
    "CARRIER_LEGAL_NAME": "Okafor Freight Systems Inc",
    "CARRIER_DOT_NUMBER": "DOT-100001",
    "CARRIER_SAFETY_SCORE": 72.0,
    "CARRIER_INSURANCE_EXPIRES_AT": "2027-06-01T00:00:00Z",
    "CARRIER_INSURANCE_LIABILITY_LIMIT_CENTS": 100000000,
    "CARRIER_CARGO_COVERAGE_LIMIT_CENTS": 175000000,
    "DEFAULT_EQUIPMENT_TYPE": "DRY_VAN",
    "DEFAULT_COMMODITY": "GENERAL",
    "DEFAULT_WEIGHT_LBS": 40000,
    "DEFAULT_DECLARED_CARGO_VALUE_CENTS": 5000000,
    "DEFAULT_DISTANCE_MILES": 1200,
    "DEFAULT_PICKUP_WINDOW_START": "2026-10-05T08:00:00Z",
    "DEFAULT_PICKUP_WINDOW_END": "2026-10-05T12:00:00Z",
    "DEFAULT_DELIVERY_DEADLINE": "2026-10-07T18:00:00Z",
    "DEFAULT_MARKET_BAND": "BALANCED",
}

# Lane keys used by the indexed scenarios.
LANE_TX_CA = "TX>CA"
LANE_TX_GA = "TX>GA"