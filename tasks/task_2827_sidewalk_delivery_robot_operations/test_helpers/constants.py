"""Domain thresholds and platform constants named by the PRD."""

# --- Delivery fee -----------------------------------------------------------
DELIVERY_FEE = {
    "BASE_FEE_CENTS": 349,
    "PER_100M_CENTS": 22,
    "CROSSING_FEE_CENTS": 35,
    "URGENCY_WINDOW_MINUTES": 45,
    "URGENCY_SURCHARGE_CENTS": 180,
    "INTERVENTION_SURCHARGE_CENTS": 95,
    "BLOCKAGE_CREDIT_CENTS_PER_MIN": 8,
    "BLOCKAGE_CREDIT_CAP_FRACTION": 0.4,
}

PAYLOAD_TIER_CENTS = {"SMALL": 0, "MEDIUM": 120, "LARGE": 260}
PAYLOAD_TIER_UPPER_LITERS = {"SMALL": 15.0, "MEDIUM": 30.0, "LARGE": 45.0}
MERCHANT_GRADE_DISCOUNT = {"STANDARD": 0.0, "PREFERRED": 0.05, "ANCHOR": 0.12}

# --- Autonomy index --------------------------------------------------------
AUTONOMY_INDEX = {
    "START_INDEX": 100,
    "INTERVENTION_PENALTY": 6,
    "ESCALATION_PENALTY_EXTRA": 4,
    "CLEAN_MISSION_CREDIT": 2,
    "ROLLING_WINDOW_MISSIONS": 5,
    "ROLLING_DECAY_FACTOR": 0.85,
    "INDEX_FLOOR": 40,
    "INDEX_CEILING": 100,
}

# --- Crossing risk score ---------------------------------------------------
CROSSING_RISK = {
    "FLOW_COEFFICIENT": 1.4,
    "FLOW_TERM_CAP": 28,
    "GRADE_HINGE_PCT": 5.0,
    "GRADE_COEFFICIENT": 3.0,
    "CURB_RAMP_CREDIT": -6,
    "SCORE_FLOOR": 0.0,
    "SCORE_CEILING": 100.0,
}
CROSSING_CONTROL_ADJUSTMENT = {
    "NONE": 0,
    "SIGNALIZED": -12,
    "UNSIGNALIZED": 10,
    "MIDBLOCK": 22,
}

# --- Route geometry --------------------------------------------------------
CLEARANCE_BUFFER_CM = 12
SPEED_DERATE_FACTOR = 0.6

# --- Robot selector / dispatch eligibility ---------------------------------
SELECTOR = {
    "MIN_BATTERY_PCT": 35.0,
    "LOW_BATTERY_PCT": 20.0,
    "MIN_ROLLING_INDEX": 70,
}

# --- Depot bay ledger ------------------------------------------------------
TURNAROUND_BUFFER_MINUTES = 15

# --- Customer remedy waterfall --------------------------------------------
DECLARED_VALUE_CAP_CENTS = 15000
REMEDY_POLICY = {
    "WEATHER": {"fee_refund_pct": 1.0, "declared_value_pct": 0.0, "goodwill_cents": 200},
    "VANDALISM": {"fee_refund_pct": 1.0, "declared_value_pct": 0.6, "goodwill_cents": 500},
    "BLOCKED_ROUTE": {"fee_refund_pct": 0.5, "declared_value_pct": 0.0, "goodwill_cents": 150},
    "ROBOT_FAULT": {"fee_refund_pct": 0.35, "declared_value_pct": 0.6, "goodwill_cents": 250},
    "LATE": {"fee_refund_pct": 0.25, "declared_value_pct": 0.0, "goodwill_cents": 150},
}

# --- Zone unit economics ---------------------------------------------------
ECONOMICS = {
    "ZONE_SHIFT_MINUTES": 600,
    "OVERHEAD_BASE_CENTS": 40000,
    "OVERHEAD_PER_UTILIZATION_POINT_CENTS": 150,
    "VARIABLE_CENTS_PER_100M": 9,
    "VARIABLE_CENTS_PER_INTERVENTION": 140,
    "UTILIZATION_CEILING_PCT": 100.0,
}

# --- Declared zone defaults ------------------------------------------------
ZONE_DEFAULTS = {
    "max_crossing_risk": 45.0,
    "takeover_confidence_threshold_pct": 35,
    "insurer_notify_threshold_cents": 25000,
}

# --- Incident reporting ----------------------------------------------------
MUNICIPAL_FILING_HOURS = 72

# --- Logical clock ---------------------------------------------------------
CLOCK_STARTUP_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Pagination ------------------------------------------------------------
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# --- Shared test literals --------------------------------------------------
TEST_DEFAULTS = {
    "BASE_CLOCK_UTC": "2026-08-03T09:00:00.000Z",
    "LID_CODE_BASE": 100000,
}

# A syntactically valid identifier that no row in an empty database can carry.
UNKNOWN_UUID = "11111111-1111-4111-8111-111111111111"
