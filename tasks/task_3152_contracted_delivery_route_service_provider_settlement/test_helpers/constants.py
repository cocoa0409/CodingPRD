"""Domain thresholds and rates named by the PRD.

Every value here is a literal the PRD states; tests must not recompute them.
"""

# §2.7 / §3.2 — vehicle eligibility tier.
STEP_VAN_STOP_CEILING = 1500

# §3.7 — tiered settlement rate cliff.
TIER_INCREMENT = 3
TIER_CEILING = 4000

# §3.8 — deduction segment cap and the two segment orders.
DEDUCTION_CAP = 50000

# §3.8 — performance multiplier tier boundaries and values.
MULTIPLIER_TIER_1_MIN = 60.00
MULTIPLIER_TIER_2_MIN = 75.00
MULTIPLIER_TIER_3_MIN = 85.00
MULTIPLIER_TOP = 1.05
MULTIPLIER_MID = 1.00
MULTIPLIER_LOW = 0.90

# §2.10 / §3.8 — composite blend weights (defaults and the two variants).
PERF_WEIGHT = 0.5
SAFETY_WEIGHT = 0.3
CX_WEIGHT = 0.2
DELIVERY_PERF_WEIGHT = 0.6
DELIVERY_SAFETY_WEIGHT = 0.25
DELIVERY_CX_WEIGHT = 0.15
SAFETY_PERF_WEIGHT = 0.4
SAFETY_SAFETY_WEIGHT = 0.4
SAFETY_CX_WEIGHT = 0.2
COMPOSITE_FLOOR = 0.00
COMPOSITE_CEILING = 100.00
MAX_SWING = 5.00

# §3.9 — renewal recommendation tier boundaries.
SAFETY_MIN_RENEW = 80.00
SAFETY_MIN_CONDITIONAL = 60.00
SERVICE_MIN_RENEW = 75.00
TRAILING_WINDOW = 4

# §3.10 — charge-back escalation.
CHARGEBACK_ESCALATION_CENTS = 200000
CHARGEBACK_ESCALATION_PCT = 10

# §3.1 / §3.3 — agreement commercial floors and renewal term.
AGREEMENT_BASE_RATE_FLOOR = 1
AGREEMENT_PACKAGE_RATE_FLOOR = 1
AGREEMENT_INSURANCE_FLOOR = 500000
RENEWAL_TERM_DAYS = 365
RENEGOTIATION_WINDOW_DAYS = 30

# §3.11 — dispute window and round budget.
DISPUTE_WINDOW_DAYS = 90
DISPUTE_ROUND_LIMIT = 2
RENEGOTIATION_ROUND_LIMIT = 3

# §2.7 / §3.2 — driver duty guard buffer.
DRIVER_GUARD_MINUTES = 1

# §2.6 / §3.1 — compliance denominators.
BRAND_MIN_PCT = 100.00
DRIVER_MIN_PCT = 100.00

# §2.12 — the server's startup logical instant.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# Common settlement-week opening used by most composite fixtures (§3.7).
WEEK_START = "2026-09-07T00:00:00Z"
WEEK_END_INSTANT = "2026-09-14T00:00:00Z"
# A clock instant strictly past WEEK_END_INSTANT, so close-accrual is permitted.
CLOCK_PAST_WEEK = "2026-09-15T00:00:00Z"

TEST_DEFAULTS = {
    "LEGAL_NAME": "Acme Route Services LLC",
    "TAX_ID": "27-1000001",
    "AREA_CODE": "TR11",
    "STATE_CODE": "TN",
    "ZIP_LOW": "372",
    "ZIP_HIGH": "374",
    "STOP_CAPACITY": 2000,
    "BASE_RATE_CENTS_PER_STOP": 22,
    "PACKAGE_RATE_CENTS": 8,
    "PEAK_SURCHARGE_CENTS": 150,
    "INSURANCE_COVERAGE_CENTS": 500000,
    "NEGOTIATED_BY": "am_001",
    "EFFECTIVE_DATE": "2026-09-03T00:00:00Z",
    "POLICY_COVERAGE_CENTS": 1000000,
    "POLICY_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "FUEL_RATE_CENTS_PER_MILE": 3,
}