"""Domain thresholds and schedule constants from the PRD's calculation rules."""

# Logical clock startup default (PRD Section 2.4)
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Offer pre-approval (PRD Section 3.2)
OFFER_MONTHS_MULT = 1.25
CONSERVATIVE_HAIRCUT = 0.70
SEASONALITY_THRESHOLD = 0.75
OFFER_ROUND_STEP_CENTS = 50_000
MIN_MONTHS_RECORDED = 12
OFFER_WINDOW_DAYS = 30

# Fee tiers and per-period minimum (PRD Section 3.3)
TIER1_CAP_CENTS = 2_500_000
TIER1_RATE = 0.11
TIER2_CAP_CENTS = 10_000_000
TIER2_RATE = 0.13
TIER3_RATE = 0.15
MIN_REPAYMENT_FRACTION_DENOM = 18

# Repayment periods (PRD Section 3.5)
MIN_REPAYMENT_PERIOD_DAYS = 60
PERIODS_TO_DELINQUENT = 2
PERIODS_TO_DEFAULT = 4

# Merchant activation minimums (PRD Section 3.1)
TENURE_MIN_DAYS = 365
LIFETIME_VOLUME_MIN_CENTS = 10_000_000

# Migration risk (PRD Section 3.7)
MIGRATION_DROP_THRESHOLD = 0.60
CHARGEBACK_SPIKE_RATIO = 0.03

# Disclosure (PRD Section 3.3)
SCHEDULED_TERM_DAYS = 1080
PACE_WINDOW_DAYS = 90
COOLING_HOURS = 24
MANDATE_STATES = ("CA", "NY", "UT", "VA")

# Loan sale waterfall (PRD Section 3.8)
SALE_RESERVE_PCT = 0.05
ENFORCEMENT_WINDOW_DAYS = 30

# Standard flat processing history: 12 monthly batches of 1,000,000 net cents
# (Sep 2025 through Aug 2026), all finalized -> avg 1,000,000/mo,
# pre-approval 1,250,000 cents.
FLAT_HISTORY_MONTHLY_NET = 1_000_000
FLAT_HISTORY_PREAPPROVED_CENTS = 1_250_000
FLAT_HISTORY_DATES = [
    "2025-09-01", "2025-10-01", "2025-11-01", "2025-12-01",
    "2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01",
    "2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01",
]

# Standard accepted terms used across fixtures
PRINCIPAL_SMALL = 500_000       # total 555,000 @ 10% holdback, fee rate 0.11
PRINCIPAL_STANDARD = 1_050_000  # total 1,165,500, per-period minimum 64,750
HOLDBACK_10 = 0.10

# Period-evaluation clock schedule after activation at the default clock
# (60 days per period starting 2026-09-01)
PERIOD_END_CLOCKS = [
    "2026-10-31T00:00:00Z",   # closes period 0
    "2026-12-30T00:00:00Z",   # closes period 1
    "2027-02-28T00:00:00Z",   # closes period 2
    "2027-04-29T00:00:00Z",   # closes period 3
]
