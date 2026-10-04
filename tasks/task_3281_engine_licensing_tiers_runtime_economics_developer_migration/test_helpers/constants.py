"""Domain thresholds — numeric constants from the PRD (§2.5, §3)."""

# Logical clock default at server startup (PRD §2.5)
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# Tier economics (PRD §3.1)
TRUST_SCORE_INITIAL = 80
TRUST_REVIEW_FLOOR = 50
TRUST_POLICY_ADVERSE_DECREMENT = 10
TRUST_AUDIT_CONVERSION_DECREMENT = 15

# Runtime fee assessment (PRD §3.4)
INSTALL_THRESHOLD = 1_000_000
REVENUE_THRESHOLD_CENTS = 100_000_000
RATE_LOW_CENTS = 20
RATE_HIGH_CENTS = 5
RATE_LOW_BAND_INSTALLS = 100_000

# Invoice settlement (PRD §3.4)
INVOICE_DUE_DAYS = 30
WAIVER_CAP_PCT = 0.5

# Creator revenue share (PRD §3.6)
SHARE_BOUNDARY_CENTS = 100_000_000
SHARE_LOW_PCT = 0.30
SHARE_HIGH_PCT = 0.25

# Upgrade risk score (PRD §3.3)
AGE_HORIZON_MONTHS = 36
API_CAP = 200

# Buyout settlement (PRD §3.8)
SEAT_MONTH_CENTS = 15_000
TENURE_FULL_WAIVER_MONTHS = 36
TENURE_REDUCED_MONTHS = 12
EARLY_TERM_REDUCED_PCT = 0.10
EARLY_TERM_FULL_PCT = 0.25

# Refund window (PRD §3.6)
REFUND_WINDOW_DAYS = 14

# Migration cooling-off (PRD §3.8)
COOLING_OFF_DAYS = 14

# Appeals (PRD §3.8)
MAX_APPEALS = 2

# Policy activation (PRD §3.5)
MIN_GRANDFATHER_WINDOW_DAYS = 30

# Pagination defaults (PRD §2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_OFFSET_DEFAULT = 0

# Standard tier config constants used across fixtures/tests. The canonical
# PERSONAL + PRO pair appearing throughout the PRD scenarios.
PERSONAL_TIER = {
    "tier_code": "PERSONAL",
    "revenue_ceiling_cents": 20_000_000,
    "funding_ceiling_cents": 20_000_000,
    "seat_minimum": 0,
    "seat_overage_cents": 0,
    "runtime_fee_exempt": True,
    "export_module_allowed": False,
    "marketplace_sell_allowed": False,
}

PRO_TIER = {
    "tier_code": "PRO",
    "revenue_ceiling_cents": 100_000_000,
    "funding_ceiling_cents": 100_000_000,
    "seat_minimum": 2,
    "seat_overage_cents": 25_000,
    "runtime_fee_exempt": False,
    "export_module_allowed": True,
    "marketplace_sell_allowed": True,
}

ENTERPRISE_TIER = {
    "tier_code": "ENTERPRISE",
    "revenue_ceiling_cents": 0,
    "funding_ceiling_cents": 0,
    "seat_minimum": 10,
    "seat_overage_cents": 40_000,
    "runtime_fee_exempt": False,
    "export_module_allowed": True,
    "marketplace_sell_allowed": True,
}

EDUCATION_TIER = {
    "tier_code": "EDUCATION",
    "revenue_ceiling_cents": 20_000_000,
    "funding_ceiling_cents": 20_000_000,
    "seat_minimum": 0,
    "seat_overage_cents": 0,
    "runtime_fee_exempt": True,
    "export_module_allowed": False,
    "marketplace_sell_allowed": False,
}
