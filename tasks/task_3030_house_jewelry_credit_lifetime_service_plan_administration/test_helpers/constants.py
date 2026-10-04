"""Domain constants named by the PRD's calculation and rule sections."""

# --- Counter credit pricing (§2.4) ---
TIER_3_REQUEST_THRESHOLD_CENTS = 1_000_000
TIER_2_REQUEST_THRESHOLD_CENTS = 500_000
TIER_1_REQUEST_THRESHOLD_CENTS = 200_000
INCOME_DOWNGRADE_THRESHOLD_CENTS = 2_500_000
ALL_STATES_KEY = "*"

# --- Deferred-interest plan economics (§2.5) ---
DAYS_PER_YEAR = 365
MONTHS_PER_QUARTER = 3
APR_PROMO_12_6M = 26.99
APR_PROMO_18_6M = 27.99
APR_PROMO_24_12M = 28.99
DEFERRAL_BPS_PROMO_12_6M = 1200
DEFERRAL_BPS_PROMO_18_6M = 1500
DEFERRAL_BPS_PROMO_24_12M = 1600
PROMO_CODE_TERMS = {
    "PROMO_12_6M": {
        "deferred_months": 6,
        "simplicity_months": 12,
        "deferral_basis_points": 1200,
        "promotional_apr_pct": 26.99,
    },
    "PROMO_18_6M": {
        "deferred_months": 6,
        "simplicity_months": 18,
        "deferral_basis_points": 1500,
        "promotional_apr_pct": 27.99,
    },
    "PROMO_24_12M": {
        "deferred_months": 12,
        "simplicity_months": 24,
        "deferral_basis_points": 1600,
        "promotional_apr_pct": 28.99,
    },
}
PROMOTIONAL_BUCKET = "PROMOTIONAL"

# --- Bench liability, routing and turnaround (§2.7) ---
WARRANTY_RESERVE_PCT = 0.07
LOSS_LIABILITY_DEFAULT_CENTS = 0
ROUTE_TABLE = {
    "STONE_LOSS": "MALCA",
    "SETTING": "JEWELCRAFT",
    "PRONG": "JEWELCRAFT",
    "RESIZE": "MASTERMELT",
    "OTHER": "MASTERMELT",
}
RUSH_SHOP_CODE = "CONRUSH"
CEILING_MULTIPLIER = 1.5
PARTIAL_BREACH_PCT = 0.05
MAJOR_BREACH_PCT = 0.15
FULL_BREACH_PCT = 0.25
BREACH_COMPENSATION_PCT = 0.05

# --- Trade-up and commission economics (§2.8) ---
TRADE_UP_CREDIT_PCT = 0.85
TRADE_UP_BONUS_PCT = 0.10
TRADE_UP_CREDIT_CAP_MULTIPLIER = 2
DEPOSIT_PCT_MIN = 0.30
DEPOSIT_PCT_MAX = 0.50
CAD_REVISION_FEE_CENTS = 2_500
FREE_REVISION_LIMIT = 2

# --- Replacement appraisal and insurance coordination (§2.9) ---
APPRAISAL_MULTIPLIER_UNREPAIRABLE = 1.04
APPRAISAL_MULTIPLIER_DEFAULT = 1.00
LAB_GROWN_FACTOR = 0.65
INSURANCE_REPLACEMENT_PCT = 0.75
INSURANCE_REPLACEMENT_CAP_PCT = 0.25

# --- Credit posture recomputation (§2.10) ---
UTIL_VIOLATION_BPS = 8_000
UTIL_WATCH_BPS = 5_000
STREAK_COMPONENT_CAP = 3

# --- Statement balances and payment allocation (§2.11) ---
MIN_FLOOR_CENTS = 5_000
MIN_BASE_PCT_LOW = 0.01
MIN_BASE_PCT_HIGH = 0.02
HIGH_BALANCE_THRESHOLD_CENTS = 200_000
TIER_FEE_PCT_HIGH = 0.03
TIER_FEE_PCT_MID = 0.02
TIER_FEE_PCT_LOW = 0.01
TIER_BOUNDARY_HIGH_CENTS = 500_000
TIER_BOUNDARY_MID_CENTS = 200_000

# --- Lifetime plan registration (§3.3) ---
REMINDER_LEAD_DAYS = 14
FIRST_CYCLE_INDEX = 1
DEFAULT_INSPECTION_INTERVAL_DAYS = 180
DEFAULT_INSPECTION_CURE_DAYS = 30
DEFAULT_STORE_HOLD_DAYS = 30

# --- Logical clock (§2.16 / §3.1) ---
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# --- Values used when building fixture graphs ---
DEFAULT_CREDIT_CAPACITY_CENTS = 5_000_000
DEFAULT_BUNDLE = {
    "bundle_code": "BUNDLE_180",
    "display_name": "Lifetime Diamond 180",
    "lifetime_plan_fee_cents": 19_900,
    "stone_limit_labor_cents": 25_000,
    "stone_limit_parts_cents": 60_000,
    "inspection_interval_days": 180,
    "inspection_cure_days": 30,
}
DEFAULT_TX_REGULATION = {
    "state_code": "TX",
    "max_plan_term_months": 60,
    "inspection_required_months": 6,
    "lapse_cure_days": 30,
    "replacement_plus_pct": 1.0,
    "max_inspection_gap_days": 210,
}
DEFAULT_REPAIR_INTAKE = {
    "failure_class": "SETTING",
    "declared_parts_cents": 40_000,
    "declared_labor_cents": 15_000,
    "declared_loss_liability_cents": 5_000,
}
# The NET_RESERVE worked example shared by the liability rules.
NET_RESERVE_WORKED_LIABILITY_CENTS = 35_000
NET_RESERVE_WORKED_RESERVE_CENTS = 2_800
NET_RESERVE_WORKED_INSURANCE_PARTS_CENTS = 37_200
NET_RESERVE_WORKED_CUSTOMER_PARTS_CENTS = 2_800
NET_RESERVE_WORKED_CUSTOMER_LABOR_CENTS = 15_000
GROSS_RESERVE_WORKED_LIABILITY_CENTS = 38_850

THRESHOLDS = {
    "TIER_3_REQUEST_THRESHOLD_CENTS": TIER_3_REQUEST_THRESHOLD_CENTS,
    "TIER_2_REQUEST_THRESHOLD_CENTS": TIER_2_REQUEST_THRESHOLD_CENTS,
    "TIER_1_REQUEST_THRESHOLD_CENTS": TIER_1_REQUEST_THRESHOLD_CENTS,
    "INCOME_DOWNGRADE_THRESHOLD_CENTS": INCOME_DOWNGRADE_THRESHOLD_CENTS,
    "UTIL_VIOLATION_BPS": UTIL_VIOLATION_BPS,
    "UTIL_WATCH_BPS": UTIL_WATCH_BPS,
    "TIER_BOUNDARY_HIGH_CENTS": TIER_BOUNDARY_HIGH_CENTS,
    "TIER_BOUNDARY_MID_CENTS": TIER_BOUNDARY_MID_CENTS,
    "HIGH_BALANCE_THRESHOLD_CENTS": HIGH_BALANCE_THRESHOLD_CENTS,
    "MIN_FLOOR_CENTS": MIN_FLOOR_CENTS,
}

TEST_DEFAULTS = {
    "STORE_CREDIT_CAPACITY_CENTS": DEFAULT_CREDIT_CAPACITY_CENTS,
    "STORE_HOLD_DAYS": DEFAULT_STORE_HOLD_DAYS,
    "INSPECTION_INTERVAL_DAYS": DEFAULT_INSPECTION_INTERVAL_DAYS,
    "INSPECTION_CURE_DAYS": DEFAULT_INSPECTION_CURE_DAYS,
    "PLAN_TERM_MONTHS": 24,
    "CUSTOMER_STATE": "TX",
    "STORE_STATE": "TX",
}

__all__ = [name for name in dir() if name.isupper()] + [
    "PROMO_CODE_TERMS",
    "DEFAULT_BUNDLE",
    "DEFAULT_TX_REGULATION",
    "DEFAULT_REPAIR_INTAKE",
    "THRESHOLDS",
    "TEST_DEFAULTS",
]