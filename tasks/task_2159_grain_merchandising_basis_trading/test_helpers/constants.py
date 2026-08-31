"""Domain thresholds and rates stated in the PRD."""

# PRD §3.3: "Each futures lot represents 5,000 bushels."
CONTRACT_UNIT_BUSHELS = 5000

# PRD §2.9 / §3.3: per-lot initial margin by commodity, in USD.
INITIAL_MARGIN_USD_PER_LOT = {
    "CORN": 1650.00,
    "SOYBEANS": 3300.00,
    "HRW_WHEAT": 2200.00,
}

# PRD §3.3: per-lot maintenance margin by commodity, in USD.
MAINTENANCE_MARGIN_USD_PER_LOT = {
    "CORN": 1500.00,
    "SOYBEANS": 3000.00,
    "HRW_WHEAT": 2000.00,
}

# PRD §2.9: inclusive posture breakpoints on credit_utilization.
POSTURE_RESTRICTED_AT = 0.8000
POSTURE_FROZEN_AT = 1.0000

# PRD §3.3: a margin call's cure window.
MARGIN_CALL_CURE_HOURS = 24

# PRD §3.7 step three: merchandising service fee tiers, keyed on the
# pre-fee gross contract value of the load.
SERVICE_FEE_TIER_1_CEILING_USD = 50000.00
SERVICE_FEE_TIER_2_CEILING_USD = 250000.00
SERVICE_FEE_TIER_1_CENTS = 3.0
SERVICE_FEE_TIER_2_CENTS = 2.0
SERVICE_FEE_TIER_3_CENTS = 1.0

# PRD §3.1: discount schedule defaults when the draft omits them.
MOISTURE_STANDARD_PCT_DEFAULT = 15.0
SHRINK_FACTOR_PCT_PER_POINT_DEFAULT = 1.18

# PRD §3.7 step two: the pinned factor evaluation order.
FACTOR_ORDER = ["MOISTURE", "TEST_WEIGHT", "FOREIGN_MATERIAL", "DAMAGE"]

# PRD §3.6: rail car turnaround buffer added to release_at.
FLEET_TURNAROUND_HOURS = 48

# PRD §3.9: roll service fee and replacement-cost administrative fee.
ROLL_SERVICE_FEE_CENTS = 2.0
REPLACEMENT_ADMIN_FEE_USD = 250.00

# PRD §3.9: delivery grace period before a default may be declared.
DEFAULT_GRACE_DAYS = 10

# PRD §2.5: the logical clock's startup reading.
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# PRD §2.3: pagination bounds.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# A well-formed UUID that never resolves to a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

TEST_DEFAULTS = {
    "CREDIT_LINE_USD": 5_000_000.00,
    "INTAKE_CAPACITY_BUSHELS": 5_000_000,
    "BID_MAX_BUSHELS": 1_000_000,
    "BID_BASIS_CENTS": -32,
    "BID_EXPIRES_AT": "2027-01-15T00:00:00Z",
    "DELIVERY_PERIOD_START": "2026-10-01",
    "DELIVERY_PERIOD_END": "2026-12-31",
    "DELIVERY_START": "2026-11-01",
    "DELIVERY_END": "2026-11-30",
    "FUTURES_MONTH": "2026-12",
    "ENTRY_PRICE_CENTS": 448,
    "SCHEDULE_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
}

# The four-factor discount schedule used by most grading scenarios.
FULL_TIERS = [
    {"factor": "MOISTURE", "direction": "ABOVE", "threshold_value": 15.0,
     "unit_step": 0.5, "rate_cents_per_bushel_per_step": 2.5},
    {"factor": "TEST_WEIGHT", "direction": "BELOW", "threshold_value": 54.0,
     "unit_step": 1.0, "rate_cents_per_bushel_per_step": 3.5},
    {"factor": "FOREIGN_MATERIAL", "direction": "ABOVE", "threshold_value": 3.0,
     "unit_step": 0.5, "rate_cents_per_bushel_per_step": 1.5},
    {"factor": "DAMAGE", "direction": "ABOVE", "threshold_value": 5.0,
     "unit_step": 1.0, "rate_cents_per_bushel_per_step": 4.0},
]

# A single-factor schedule: test weight only, 3.5 cents per step.
TEST_WEIGHT_TIERS = [
    {"factor": "TEST_WEIGHT", "direction": "BELOW", "threshold_value": 54.0,
     "unit_step": 1.0, "rate_cents_per_bushel_per_step": 3.5},
]

# The same single factor at a dearer rate, for supersession scenarios.
TEST_WEIGHT_TIERS_DEAR = [
    {"factor": "TEST_WEIGHT", "direction": "BELOW", "threshold_value": 54.0,
     "unit_step": 1.0, "rate_cents_per_bushel_per_step": 10.0},
]

# Probe readings that draw zero discount under FULL_TIERS.
CLEAN_LOAD = {
    "moisture_pct": 15.0,
    "test_weight_lbs": 56.0,
    "foreign_material_pct": 2.0,
    "damage_pct": 0.0,
}
