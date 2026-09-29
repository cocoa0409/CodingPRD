"""Domain thresholds and literal defaults declared by the PRD calculations."""

# Territory protection geometry
KM_PER_DEG_LAT = 111.0
KM_PER_DEG_LNG = 85.0
PROTECTION_BUFFER_KM = 0.5
RELOCATION_REVISION_LIMIT = 2

# Membership pricing
MULTI_CLUB_CREDIT_PCT = 0.015
MAX_FRANCHISE_DISCOUNT_PCT = 0.30
PROMO_COOLING_GAP_DAYS = 7

# Royalty reporting
BRAND_STANDARD_DUES_CENTS = 4500
ROYALTY_VARIANCE_TOLERANCE_PCT = 5.00

# Facility inspections
BRAND_REFRESH_CYCLE_MONTHS = 60
ACCELERATED_REFRESH_CYCLE_MONTHS = 42
ACCELERATED_MANDATE_DATE = "2020-01-01"
REMEDIATION_SCORE_THRESHOLD = 70

# Guest usage settlement waterfall
ADMIN_HOLD_PCT = 0.08
REBATE_TIER_1_FLOOR = 50000
REBATE_TIER_2_FLOOR = 100000

# Dues ledger projection
DELINQUENCY_DAYS_THRESHOLD = 30
COLLECTIONS_DAYS_THRESHOLD = 60
COLLECTIONS_WATCH_SHARE = 0.15

# Cancellation settlement
EARLY_TERM_MONTHLY_PCT = 0.5
EARLY_TERM_FEE_CAP_CENTS = 15000

# Transfers
TRANSFER_FEE_BASE_CENTS = 2500
CROSS_FRANCHISE_TRANSFER_PCT = 0.5
TRANSFER_FEE_DUE_DAYS = 15

# Franchisee standing
INSPECTION_FAIL_PENALTY = 20
COLLECTIONS_WATCH_PENALTY = 20
DISPUTED_ROYALTY_PENALTY = 10
PROBATION_SCORE_THRESHOLD = 70

# Statutory membership rules keyed by state_code
STATE_STATUTES = {
    "CA": {
        "cooling_off_days": 5,
        "max_notice_days": 30,
        "prorate_refund": True,
        "allow_cross_state_transfer": False,
    },
    "TX": {
        "cooling_off_days": 3,
        "max_notice_days": 30,
        "prorate_refund": True,
        "allow_cross_state_transfer": True,
    },
    "NY": {
        "cooling_off_days": 3,
        "max_notice_days": 15,
        "prorate_refund": False,
        "allow_cross_state_transfer": True,
    },
}

# Logical clock
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"
INITIAL_CLOCK_DATE = "2026-08-01"

# Field-level decimal precision declared by the PRD
PRECISION = {
    "center_lat": 4,
    "center_lng": 4,
    "protected_radius_km": 1,
    "discount_pct": 3,
    "corporate_credit_pct": 3,
    "variance_pct": 2,
    "encroachment_km": 3,
}

# Frequently reused literal test inputs
TEST_DEFAULTS = {
    "ROYALTY_RATE_BPS": 650,
    "GUEST_FEE_CENTS": 1250,
    "PLAN_CODE": "CORE12",
    "MONTHLY_DUES_CENTS": 4500,
    "INITIATION_FEE_CENTS": 4900,
    "TERM_MONTHS": 12,
    "CANCELLATION_NOTICE_DAYS": 30,
    "FLOOR_PRICE_CENTS": 3600,
    "TERRITORY_LAT": 34.0,
    "TERRITORY_LNG": -118.0,
    "TERRITORY_RADIUS_KM": 5.0,
    "MODERN_OPENED_ON": "2021-06-01",
    "LEGACY_OPENED_ON": "2019-06-01",
}

# Pagination envelope defaults
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1
