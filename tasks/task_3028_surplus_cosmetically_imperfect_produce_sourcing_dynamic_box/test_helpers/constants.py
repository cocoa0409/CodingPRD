"""Domain thresholds and pricing constants stated in the PRD.

Every value here is quoted from the PRD's own prose (§2.5, §2.8, §3.3, §3.4,
§3.6, §3.7, §3.8, §3.9) so tests can assert against named thresholds instead
of magic numbers.
"""

# --- Box composition (§2.8) -------------------------------------------------
BOX_UNIT_TARGET = 10
PREFERENCE_SHARE_UNITS = 6          # ceil(0.60 * 10)
FILLER_SHARE_UNITS = 2              # ceil(0.20 * 10)
SPECIALTY_SHARE_UNITS = 2           # target - preference - filler
MIN_UNITS_PER_LINE = 2
MAX_LINES_PER_BOX = 6

# --- Order pricing (§3.6) ---------------------------------------------------
SERVICE_FEE_CENTS = 599
TAX_RATE = 0.05
ORDER_DISCOUNT_GATE_CENTS = 5000
ORDER_DISCOUNT_RATE = 0.10

# --- Display price (§3.6) ---------------------------------------------------
GRADE_RETAIL_MULTIPLIER = {
    "OFF_SPEC": 1.50,
    "SURPLUS": 1.60,
    "SHORT_DATED": 1.75,
    "COSMETIC": 1.80,
    "CONVENTIONAL": 1.40,
}
CATEGORY_FLOOR_MULTIPLIER = {
    "FRUIT": 1.25,
    "VEGETABLE": 1.25,
    "DAIRY": 1.20,
    "BAKERY": 1.35,
    "PANTRY": 1.30,
    "BEVERAGE": 1.30,
}

# --- Billing weight (§3.4 / §3.6) -------------------------------------------
MIN_BILLING_WEIGHT_GRAMS = {
    "FRUIT": 120,
    "VEGETABLE": 120,
    "DAIRY": 150,
    "BAKERY": 200,
    "PANTRY": 100,
    "BEVERAGE": 300,
}

# --- Cold chain (§3.7) ------------------------------------------------------
LANE_TRANSIT_DAYS = {"NE": 2, "MW": 3, "SO": 3, "WE": 4}
COLD_WEIGHT_REQUIRED_GRAMS = 1200
INSULATED_TRANSIT_MIN_DAYS = 3
COOLANT_UNIT_DIVISOR = 1500
NON_COLD_THERMAL_ALLOWANCE_GRAMS = 250
WARM_LANES = {"WE", "SO"}

# --- Order window (§3.4) ----------------------------------------------------
CUTOFF_LEAD_HOURS = {"NE": 36, "MW": 48, "SO": 48, "WE": 60}
BUILD_WINDOW_HOURS = 72
DEGRADED_BUILD_WINDOW_HOURS = 144
HOURS_PER_CYCLE = {"WEEKLY": 168, "BIWEEKLY": 336, "MONTHLY": 720}

# --- Quality credits (§3.3) -------------------------------------------------
FLAT_UNIT_CREDIT_CENTS = {
    "SPOILED": 300,
    "DAMAGED": 350,
    "MISSING_ITEM": 300,
    "TEMPERATURE_ABUSE": 400,
}
CREDIT_GRADE_MULTIPLIER = {
    "OFF_SPEC": 1.00,
    "SURPLUS": 1.00,
    "SHORT_DATED": 1.10,
    "COSMETIC": 1.15,
}
PER_CLAIM_GRACE_CENTS = 200
CLAIM_WINDOW_DAYS = 7
CLAIM_WINDOW_DAYS_ESCALATION = 7
LINE_CAP_RATE = 0.75

# --- Reliability (§3.1) -----------------------------------------------------
ON_TIME_WEIGHT = 0.40
ACCEPTANCE_WEIGHT = 0.40
QUALITY_WEIGHT = 0.20
PREFERRED_FLOOR_BP = 9000
STANDARD_FLOOR_BP = 7500
ON_WATCH_FLOOR_BP = 6000
MAX_PAUSE_HOPS = 4

# --- Pagination defaults (§2.3) ---------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100

# --- Test-driving defaults --------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
CYCLE_ADVANCE_CLOCK = "2026-09-04T12:00:00Z"