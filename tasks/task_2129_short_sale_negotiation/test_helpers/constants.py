"""Domain thresholds and canonical test data drawn from the PRD's stated rules."""

# ─── Numeric thresholds stated in the PRD ─────────────
THRESHOLDS = {
    # Settlement net sheet
    "TRANSFER_TAX_PCT": 0.0075,
    "SERVICER_COMMISSION_CAP_PCT": 0.055,
    "RELOCATION_TIER_HIGH_MIN_CENTS": 20_000_000,
    "RELOCATION_TIER_MID_MIN_CENTS": 10_000_000,
    "RELOCATION_HIGH_CENTS": 300_000,
    "RELOCATION_MID_CENTS": 200_000,
    "RELOCATION_LOW_CENTS": 100_000,
    # Hardship score
    "DEFICIT_WEIGHT": 30,
    "RESERVE_WEIGHT": 20,
    "DOC_WEIGHT": 10,
    "RESERVE_CAP_MONTHS": 6,
    "HARDSHIP_MIN_SCORE": 55.00,
    # Servicer floor
    "MIN_NET_RATIO_GSE": 0.88,
    "MIN_NET_RATIO_PORTFOLIO": 0.84,
    "MIN_NET_RATIO_FHA": 0.86,
    "UPB_FLOOR_RATIO": 0.60,
    # Marketing / negotiation
    "MIN_MARKETING_DAYS": 15,
    "PRICE_REDUCTION_TRIGGER_COUNT": 2,
    "MAX_NEGOTIATION_ROUNDS": 3,
    # Disputes
    "DISPUTE_MIN_VARIANCE_PCT": 0.05,
    "DISPUTE_MIN_COMPARABLES": 3,
    # Documents
    "DOCUMENT_MAX_AGE_DAYS": 90,
    # Approval letters
    "APPROVAL_TERM_DAYS": 45,
    "MAX_CUMULATIVE_EXTENSION_DAYS": 60,
    # Vendor scheduling
    "VENDOR_INSPECTION_BUFFER_MINUTES": 60,
    # Pagination
    "DEFAULT_LIMIT": 10,
    "MAX_LIMIT": 100,
}

REASON_WEIGHT = {
    "JOB_LOSS": 40,
    "MEDICAL": 35,
    "DIVORCE": 30,
    "INCOME_REDUCTION": 25,
    "RELOCATION": 20,
    "OTHER": 10,
}

REQUIRED_DOCUMENT_TYPES = [
    "HARDSHIP_LETTER",
    "FINANCIAL_WORKSHEET",
    "BANK_STATEMENT",
    "AUTHORIZATION_FORM",
]

# ─── Logical-clock instants used across the suite ─────
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_LISTED = "2026-08-05T00:00:00Z"          # listings open here
CLOCK_VALUATION_DAY = "2026-08-06T00:00:00Z"
CLOCK_DOM_14 = "2026-08-19T00:00:00Z"          # days_on_market == 14
CLOCK_DOM_15 = "2026-08-20T00:00:00Z"          # days_on_market == 15
CLOCK_DOM_19 = "2026-08-24T00:00:00Z"          # days_on_market == 19
CLOCK_BEFORE_DEADLINE = "2026-09-15T00:00:00Z"
CLOCK_AFTER_DEADLINE = "2026-10-09T00:00:00Z"

# ─── Canonical fixture values ─────────────────────────
TEST_DEFAULTS = {
    "UPB_CENTS": 26_800_000,
    "PORTFOLIO_UPB_CENTS": 42_000_000,
    "SERVICER_NAME": "Cascade Servicing",
    "LIST_PRICE_CENTS": 25_900_000,
    "COMMISSION_PCT": 0.06,
    "OFFER_PRICE_CENTS": 24_500_041,
    "EARNEST_MONEY_CENTS": 500_000,
    "REQUESTED_CLOSING_DAYS": 45,
    "TITLE_ESCROW_CENTS": 187_500,
    "PROPERTY_TAX_ARREARS_CENTS": 412_300,
    "HOA_ARREARS_CENTS": 96_450,
    "LIEN_BALANCE_CENTS": 3_500_000,
    "LIEN_DEMAND_CENTS": 900_000,
    "LIEN_CONTRIBUTION_CENTS": 600_000,
    "MI_CONTRIBUTION_CENTS": 750_000,
    "VALUATION_VALUE_CENTS": 25_200_000,
    "DOC_ISSUED_ON": "2026-07-20T00:00:00Z",
    "HOLDER_USER_ID": "jlh-700",
}

# Expected outcomes of the canonical chain, pre-computed from the PRD's formulas.
EXPECTED = {
    # minimum acceptable net on a GSE case, valuation 25_200_000, UPB 26_800_000
    "MIN_NET_GSE_NO_MI": 22_176_000,
    # ... same case once an approved MI claim credits 750_000
    "MIN_NET_GSE_WITH_MI": 21_426_000,
    # PRELIMINARY sheet, offer 24_500_041, commission 0.06, one lien demanded 900_000
    "PRELIM_GROSS_DEDUCTIONS": 3_250_002,
    "PRELIM_BASE_NET": 21_250_039,
    "PRELIM_NET_PROCEEDS": 20_950_039,
    # FINAL sheet, same offer, commission clamped to 0.055, lien contribution
    # 600_000, MI credit 750_000
    "FINAL_GROSS_DEDUCTIONS": 2_827_502,
    "FINAL_BASE_NET": 22_422_539,
    "FINAL_NET_PROCEEDS": 22_122_539,
    # closing deadline for a letter issued at 2026-08-24
    "CLOSING_DEADLINE": "2026-10-08T00:00:00.000Z",
}
