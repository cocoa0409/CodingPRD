"""Named thresholds, defaults and fixed literals drawn from the specification."""

# --- logical clock -----------------------------------------------------------
CLOCK_AT_PROCESS_START = "2026-08-01T00:00:00Z"

# --- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- site defaults -----------------------------------------------------------
DEFAULT_TARGET_INTENSITY_KG_PER_1K_MEALS = 10.000
SITE_CODE_MIN_LENGTH = 2
SITE_CODE_MAX_LENGTH = 12

# --- tracking station defaults ----------------------------------------------
DEFAULT_TARE_GRAMS = 0
DEFAULT_CAPTURE_LOCK_SECONDS = 30
MIN_CAPTURE_LOCK_SECONDS = 0
MAX_CAPTURE_LOCK_SECONDS = 600
STATION_TURNAROUND_SECONDS = 60

# --- capture bounds ----------------------------------------------------------
MIN_WEIGHT_GRAMS = 1
MAX_WEIGHT_GRAMS = 200000

# --- recipe costing ----------------------------------------------------------
YIELD_DECIMALS = 3

# --- coaching ----------------------------------------------------------------
COACHING_INTENSITY_THRESHOLD = 12.000
HIGH_SEVERITY_INTENSITY = 18.000
OVERPRODUCTION_SPIKE_GRAMS = 5000
ESCALATION_ALERT_COUNT = 3

# --- leaderboard -------------------------------------------------------------
INTENSITY_PENALTY_PER_KG = 4.0
PENALTY_CAP = 60.0
COMPLIANCE_WEIGHT = 25.0
PRE_CONSUMER_BONUS = 3.0
PRE_CONSUMER_BONUS_THRESHOLD = 0.60
LEADERBOARD_MIN_SCORE = 0.0
LEADERBOARD_MAX_SCORE = 100.0

# --- settlement --------------------------------------------------------------
GRAMS_PER_TONNE = 1000000
SURCHARGE_TIER_1_CENTS = 5000
SURCHARGE_TIER_2_CENTS = 15000
SURCHARGE_RATE_LOW = 0.00
SURCHARGE_RATE_MID = 0.06
SURCHARGE_RATE_HIGH = 0.09
VARIANCE_TOLERANCE_PCT = 5.00
VARIANCE_CREDIT_RATE = 0.10

# --- data quality ------------------------------------------------------------
DUPLICATE_WINDOW_SECONDS = 300
OUTLIER_GRAMS_THRESHOLD = 25000

# --- fixture defaults --------------------------------------------------------
TEST_DEFAULTS = {
    "site_name": "Harbor Kitchen",
    "site_code": "HK-01",
    "region_code": "NE",
    "second_site_name": "Hillside Kitchen",
    "second_site_code": "HK-02",
    "prep_station_code": "PREP-1",
    "dish_station_code": "DISH-1",
    "calibration_due_at": "2026-12-31T00:00:00Z",
    "food_type_name": "Chicken Breast",
    "food_type_category": "PROTEIN",
    "default_cost_per_kg_cents": 640,
    "donation_shelf_life_hours": 720,
    "shift_date": "2026-08-01",
    "shift_code": "AM",
    "meals_served": 250,
    "hauler_name": "Green Haul",
    "rate_cents_per_tonne": 52000,
    "stop_fee_cents": 1800,
    "capacity_kg_per_pickup": 500,
}
