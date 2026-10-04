"""Domain constants — numeric thresholds, windows, and shared fixtures' figures (PRD §2.5, §2.7, §3)."""

# Logical clock startup default (PRD §2.5).
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# Market dominance threshold on both RVC ratio variants (PRD §3.2, §3.3).
MARKET_DOMINANCE_RVC_THRESHOLD = 1.8000

# Revenue adequacy: Board's cost of capital in basis points (PRD §3.1).
COST_OF_CAPITAL_BPS = 1140

# Prescription floor factors by contested-year finding (PRD §3.3).
ADEQUACY_FLOOR_RVC_ADEQUATE = 1.0000
ADEQUACY_FLOOR_RVC_INADEQUATE = 1.1000

# Track selection / relief caps in cents (PRD §3.2, §3.3).
THREE_BENCHMARK_RELIEF_CAP_CENTS = 100000000
SIMPLIFIED_SAC_RELIEF_CAP_CENTS = 400000000

# Merger public-interest score bands (PRD §3.6).
APPROVE_THRESHOLD = 60.00
CONDITIONS_THRESHOLD = 45.00

# Durations and windows in days (PRD §3.5, §3.6, §3.7, §3.8).
MERGER_COMMENT_PERIOD_DAYS = 45
ESO_DURATION_DAYS = 60
NITU_WINDOW_DAYS = 180
SERVICE_FAILURE_WINDOW_DAYS = 84

# Interchange constraints (PRD §3.8).
INTERCHANGE_DISTANCE_LIMIT_MILES = 30
INTERCHANGE_SLOT_CAPACITY = 4

# Well-formed but never-registered identifier used for 404 probes.
NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"

# Shipper party identifiers (opaque party ids, not entity ids — PRD §2.1).
SHIPPER_ADA = "shp-ada"
SHIPPER_GAL = "shp-gal"
SHIPPER_BOB = "shp-bob"
SHIPPER_OTH = "shp-oth"

# Standard annual-report filings.
# Single 2025 filing -> current-year ROI 1000 bps -> INADEQUATE (PRD §3.1).
FINDING_2025_SINGLE = {
    "fiscal_year": 2025,
    "operating_revenue_cents": 1000000000,
    "operating_expense_cents": 800000000,
    "net_investment_cents": 2000000000,
}
# Five filings 2021-2025 -> five-year average 1180 bps -> ADEQUATE (PRD §3.1).
FINDINGS_2021_2025 = [
    {"fiscal_year": 2021, "operating_revenue_cents": 620000000,
     "operating_expense_cents": 500000000, "net_investment_cents": 1000000000},
    {"fiscal_year": 2022, "operating_revenue_cents": 600000000,
     "operating_expense_cents": 500000000, "net_investment_cents": 800000000},
    {"fiscal_year": 2023, "operating_revenue_cents": 565000000,
     "operating_expense_cents": 500000000, "net_investment_cents": 500000000},
    {"fiscal_year": 2024, "operating_revenue_cents": 730000000,
     "operating_expense_cents": 500000000, "net_investment_cents": 2000000000},
    {"fiscal_year": 2025, "operating_revenue_cents": 1000000000,
     "operating_expense_cents": 800000000, "net_investment_cents": 2000000000},
]

# Clock readings used across temporal scenarios.
CLOCK_ESO_PRE_EXPIRY = "2026-10-30T23:59:59Z"
CLOCK_ESO_EXPIRY = "2026-10-31T00:00:00Z"
CLOCK_MERGER_COMMENT_CLOSED = "2026-10-16T00:00:00Z"
CLOCK_NITU_EXPIRY = "2027-02-28T00:00:00Z"
CLOCK_NITU_EXPIRED = "2027-03-01T00:00:00Z"
