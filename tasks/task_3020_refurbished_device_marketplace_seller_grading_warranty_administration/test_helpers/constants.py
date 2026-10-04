"""Domain thresholds and seeded marketplace constants.

Every value below is a number the requirement document pins explicitly.
"""

# --- Logical clock ---------------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# --- Seller onboarding -----------------------------------------------------
PASS_SCORE_THRESHOLD = 70          # audit_score >= 70 approves
REWORK_SCORE_CEILING = 69          # audit_score <= 69 loops back to APPLICANT
AUDIT_SCOPE_NOTE_MAX = 500
COUNTRY_CODE_LEN = 2

# --- Listing eligibility ---------------------------------------------------
HARD_BATTERY_FLOOR_PCT = 80
BATTERY_MIN_PCT = 1
BATTERY_MAX_PCT = 100
PRICE_DEVIATION_PCT = 50
PROVENANCE_DIGEST_LEN = 64
IMEI_LEN = 15

# --- Marketplace model catalogue (filed via the catalogue endpoints) --------
# The supported-model catalog and its per-model floor price.  The catalogue is
# operator-owned policy filed through the declared catalogue endpoints before a
# test submits a listing, never a preload inside the server: PRD §3.2 makes a
# submission admissible only while its `model_code` is present in the catalog.
MODEL_CATALOG_FLOOR_CENTS = {
    "APL-IP13-128": 120000,
}
MODEL_CATALOG = set(MODEL_CATALOG_FLOOR_CENTS) | {"APL-IP14-256", "SAM-GS22-128"}

# --- Seeded blocklists -----------------------------------------------------
STOLEN_DEVICE_BLOCKLIST = {"000000000000000"}
COUNTERFEIT_DEVICE_BLOCKLIST = {"111111111111111"}

# --- Warranty --------------------------------------------------------------
DEFAULT_WARRANTY_PERIOD_DAYS = 180
DEFAULT_UNIT_RESERVE_PER_DAY_CENTS = 1800
DEFAULT_RESERVED_UNITS = 1
CLAIM_RESERVE_CAP_CENTS = 90000
CLAIM_RESERVE_BASE_CENTS = 25000
CLAIM_RESERVE_PER_DAY_MULTIPLIER = 151
ON_TIME_WINDOW_DAYS = 21
REPAIR_OBLIGATION_CAP_CENTS = 25000
REPLACE_OBLIGATION_CAP_CENTS = 90000
RETURN_SLOT_SECONDS = 86400

# --- Replacement settlement ------------------------------------------------
INBOUND_SHIPPING_CENTS = 5600
MARKETPLACE_FVF_RATE = 0.09
REFUSED_FUNDED_CENTS = 90000
BUYER_GOODWILL_RATE = 0.30
REPLACEMENT_WARRANTY_PERIOD_DAYS = 180

# --- Service scoring -------------------------------------------------------
WEIGHT_CLAIM_FAILURE = 0.35
WEIGHT_ON_TIME_RESOLUTION = 0.30
WEIGHT_GRADING_COMPLIANCE = 0.25
WEIGHT_RETURN_RATE = 0.10
ELITE_THRESHOLD = 85.00
STANDARD_THRESHOLD = 70.00
SUSPENSION_THRESHOLD = 55.00
MINIMUM_SECTION_DAYS = 90

# --- Constraint exposure ---------------------------------------------------
CONSTRAINT_VIOLATION_UNIT_CENTS = 9600
UNITS_DENOMINATOR = 300
DOOR_UNITS = 100

# --- Governance ceiling ----------------------------------------------------
MINIMUM_TRIGGERS = 5
TRIGGERS_CEILING = 99

# --- Reinstatement ramp ----------------------------------------------------
REINSTATEMENT_WINDOW_DAYS = 1
ESCALATION_POINTS_PER_STEP = 20.0
UNSCORED_SELLER_LATEST_SCORE_PCT = 100.0

# --- Trade-in pricing ------------------------------------------------------
TRADE_IN_BASE_CENTS = 38000
GRADE_STEP_PENALTY_CENTS = 2500
INSPECTION_FEE_CENTS = 1500
INSPECTION_FEE_PCT = 0.07
INSPECTED_BATTERY_HEALTH_REJECT_PCT = 70
ACCEPTANCE_WINDOW_DAYS = 7

COSMETIC_DEDUCT_TABLE = {
    "FLAWLESS": 0,
    "GOOD": 1800,
    "FAIR": 5200,
    "POOR": 11000,
}
FUNCTIONAL_DEDUCT_TABLE = {
    "FULLY_FUNCTIONAL": 0,
    "MINOR_FAULTS": 4200,
    "MAJOR_FAULTS": 13500,
}
LOCK_DEDUCT_TABLE = {
    "UNLOCKED": 0,
    "UNKNOWN": 4500,
    "LOCKED": 9000,
}
COSMETIC_ORDER = {"FLAWLESS": 0, "GOOD": 1, "FAIR": 2, "POOR": 3}
FUNCTIONAL_ORDER = {
    "FULLY_FUNCTIONAL": 0,
    "MINOR_FAULTS": 1,
    "MAJOR_FAULTS": 2,
}

# --- Buy box ---------------------------------------------------------------
BUY_BOX_MULTIPLIERS = {
    "ELITE": 1.00,
    "STANDARD": 0.70,
    "PROBATION": 0.40,
    "SUSPENDED": 0.00,
}
BUY_BOX_MULTIPLIER_BY_SCORE = (
    (95.00, 1.00),
    (85.00, 0.70),
    (70.00, 0.40),
)

# --- Pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Test defaults ---------------------------------------------------------
TEST_DEFAULTS = {
    "CAPACITY_UNITS": 500,
    "THROUGHPUT": 400,
    "LIST_PRICE_CENTS": 150000,
    "BATTERY_HEALTH_PCT": 88,
    "AUDIT_SCORE": 88,
    "REPAIR_OBLIGATION_CENTS": 18000,
    "RETURN_SHIPMENT_CENTS": 4500,
}