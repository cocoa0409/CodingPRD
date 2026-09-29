"""Domain thresholds and pinned numeric constants taken from the PRD."""

# Statistical baseline / method selection.
INTERMITTENT_CV_THRESHOLD = 0.75

# Consensus swing guardrail.
MAX_SWING_PCT = 25

# Revision and reopen bounds.
MAX_REVISION_ROUNDS = 3
MAX_REOPENS = 2

# Inventory policy.
DAYS_PER_MONTH = 30
SERVICE_LEVEL_Z_TIERS = [
    (99.0, 2.33),
    (97.5, 1.96),
    (95.0, 1.65),
    (90.0, 1.28),
]
SERVICE_LEVEL_Z_FLOOR = 0.84

# Capacity calendar.
CHANGEOVER_BUFFER_DAYS = 2

# Hours to units conversion.
HOURS_ROUNDING_DP = 6

# Rationing waterfall.
PROTECTED_RANK = 2

# Scenario gap closure.
CAPACITY_HOURLY_COST_CENTS = 25000
TRADE_TIER_1_CENTS = 1000000
TRADE_TIER_2_CENTS = 5000000
TRADE_RATE_TIER_1_PCT = 6.0
TRADE_RATE_TIER_2_PCT = 8.0
TRADE_RATE_BASE_PCT = 4.0

# Cycle posture.
AT_RISK_CONSTRAINED_PLAN_MIN = 1

# Accuracy roll-up.
BIAS_THRESHOLD_PCT = 5.00
GRADE_A_MAX = 10.00
GRADE_B_MAX = 20.00
GRADE_C_MAX = 35.00

# The logical clock reads exactly this instant before any request repositions it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Item creation defaults.
DEFAULT_NPI_RAMP_PCT = 100
DEFAULT_SERVICE_LEVEL_TARGET_PCT = 95.0
DEFAULT_DEMAND_CV = 0.30
DEFAULT_LEAD_TIME_DAYS = 30
DEFAULT_LIFECYCLE_STATE = "MATURE"

# Pagination.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Operator identities used consistently across the fixtures.
ADMIN_USER_ID = "admin-1"
PLANNER_USER_ID = "planner-1"
LEAD_USER_ID = "lead-1"
SUPPLY_USER_ID = "supply-1"
EXEC_USER_ID = "exec-1"

TEST_DEFAULTS = {
    "FAMILY_UNITS_PER_HOUR": 100,
    "FAMILY_MAX_MONTHLY_HOURS": 800,
    "ITEM_UNIT_PRICE_CENTS": 1000,
    "ITEM_UNIT_COST_CENTS": 400,
    "ITEM_MATERIAL_SUPPLY_CAP_UNITS": 100000,
    "ITEM_AVG_MONTHLY_DEMAND_UNITS": 1000,
    "CUSTOMER_PRIORITY_RANK": 3,
    "HORIZON_MONTH": "2026-09",
}
