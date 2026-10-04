"""Domain thresholds — numeric constants from the PRD's calculations."""

# ─── Payout grid ──────────────────────────────────────
GRID_TIER_1_BASE_BPS = 7000
GRID_TIER_2_BASE_BPS = 8000
GRID_TIER_3_BASE_BPS = 9000
GRID_TIER_1_CEILING_CENTS = 100_000_000
GRID_TIER_2_CEILING_CENTS = 250_000_000

PRODUCT_DELTA_BPS = {
    "EQUITY": 0,
    "MUTUAL_FUND": -500,
    "ANNUITY": -700,
    "BROKERAGE_TRAIL": -300,
    "ADVISORY": 500,
}

AFFILIATION_MODEL_OFFSET_BPS = {
    "IC": 0,
    "EMPLOYEE": 500,
    "HYBRID": 250,
    "INSTITUTIONAL": 6500,
}

MAX_RATE_BPS = 9000
MIN_RATE_BPS = 500

# ─── Net settlement waterfall ─────────────────────────
PASS_THROUGH_TECHNOLOGY_FLAT_CENTS = 3_000_000
PASS_THROUGH_CLEARING_FLAT_CENTS = 500_000
PASS_THROUGH_REGULATORY_FLAT_CENTS = 600_000
PASS_THROUGH_TECHNOLOGY_PCT_BPS = 200
PASS_THROUGH_CLEARING_PCT_BPS = 100
PASS_THROUGH_REGULATORY_PCT_BPS = 50

EO_RATE_BPS = {
    "STANDARD": 120,
    "PREMIUM": 350,
    "LIMITED": 900,
}

SUPERVISORY_OVERRIDE_BPS = {
    "IC": 0,
    "EMPLOYEE": 0,
    "HYBRID": 100,
    "INSTITUTIONAL": 250,
}

ANNUAL_PAYOUT_CAP_CENTS = 500_000_000

# ─── Loans ────────────────────────────────────────────
LPL_PARITY_PRINCIPAL_CAP_CENTS = 50_000_000
MILESTONE_WINDOW_MONTHS = 12

# ─── Advisory fee levelization ────────────────────────
FEE_LEVEL_TARGET_BPS = 85
ADVISORY_REBATE_BAND_BPS = {
    "band_1": 6000,   # 0 <= portability < 6000
    "band_2": 7000,   # 6000 <= portability < 8000
    "band_3": 8000,   # 8000 <= portability <= 10000
}
LEVELIZATION_FEE_CAP_CENTS = 30_000_000

# ─── Retention contest ────────────────────────────────
RETENTION_TARGET_BPS = 7000
RETENTION_CREDIT_CAP_BPS = 200
LPL_PARITY_BOOK_CAP_CENTS = 200_000_000

# ─── Portability gates ────────────────────────────────
AFFILIATION_PORTABILITY_MIN_BPS = 5000
AFFILIATION_PORTABILITY_PROTOCOL_BPS = 7000
BOOK_TRANSFER_PORTABILITY_MIN_BPS = 6000

# ─── Transfer hold ────────────────────────────────────
TRANSFER_HOLD_HOURS = 24

# ─── Test defaults ────────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "BRANCH_CODE": "SUP-1",
    "BRANCH_NAME": "Superset Wealth",
    "TRANSMITTAL_ACCOUNT": "TA-4471",
    "OSJ_NAME": "Superset OSJ",
    "ANNUAL_FEE_BPS": 85,
}

# Reusable fixture constants named so tests read in domain terms.
GRID_TIER_CEILINGS = (GRID_TIER_1_CEILING_CENTS, GRID_TIER_2_CEILING_CENTS)