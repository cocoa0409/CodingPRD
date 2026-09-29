"""Business constants, canonical literals and the shared fixture vocabulary.

Every literal here is taken from the PRD: the logical clock epoch, the rounding
denominators, the tolerance bands, and the calendar/instant formats the API
declares (calendar dates as YYYY-MM-DD, instants as ISO 8601 UTC with exactly
three fractional digits).
"""

# ---------------------------------------------------------------- clock ----
# "Before any call the clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"

# ------------------------------------------------- calculation constants ----
BPS_DENOMINATOR = 10_000
ADMIN_FEE_BAND_BREAK_CENTS = 5_000_000
DAYS_PER_YEAR = 365
WARN_BAND_BPS = 500
VARIANCE_TOLERANCE_BPS = 200

# ------------------------------------------------------------ pagination ----
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ------------------------------------------------------- tier vocabulary ----
# The ELITE tier used by every fixture. reversal_posture_limit is 2 (the PRD
# default) unless a test pins it to 1 to make the posture flip observable.
ELITE_TIER = {
    "tier_code": "ELITE",
    "member_share_bps": 7500,
    "gpo_retention_bps": 2500,
    "admin_fee_bps_low": 300,
    "admin_fee_bps_high": 150,
    "compliance_min_ratio_bps": 8000,
    "markup_cap_bps": 700,
    "dispute_window_days": 45,
    "reversal_posture_limit": 2,
}

# ------------------------------------------------ distributor and member ----
DISTRIBUTOR_NAME = "Metro Foodservice"
DISTRIBUTOR_DBA_CODE = "METRO-01"
DISTRIBUTOR_MARKUP_BPS = 900          # min(900, markup_cap 700) == 700
MEMBER_LEGAL_NAME = "Harbor Grill LLC"
MEMBER_COMMITTED_ANNUAL_SPEND_CENTS = 20_000_000
SIGNATORY_NAME = "A Ruiz"

# --------------------------------------------------------- letter window ----
# Half-open [effective_from, effective_to); brackets the clock epoch.
LETTER_FROM = "2026-01-01T00:00:00.000Z"
LETTER_TO = "2028-01-01T00:00:00.000Z"

# ----------------------------------------------------------- deal / item ----
DEAL_MANUFACTURER_NAME = "Prairie Beef Co"
DEAL_CODE = "PBC-2026"
DEAL_FROM = "2026-01-01"
DEAL_TO = "2026-12-31"
REQUIRED_PURCHASE_WINDOW_DAYS = 60

SECOND_DEAL_MANUFACTURER_NAME = "Prairie Fries Co"
SECOND_DEAL_CODE = "PBF-2026"

BEEF_SKU = "PBC-PATTY-4OZ"
BEEF_KEY = "BEEF-PATTY-4OZ-CS40"
BEEF_PACK_SIZE = 40
BEEF_BASELINE_UNIT_COST_CENTS = 9800
BEEF_CONTRACT_UNIT_COST_CENTS = 8900

FRIES_SKU = "PBF-FRY-SS"
FRIES_KEY = "FRIES-SHOESTRING-CS30"
FRIES_PACK_SIZE = 30
FRIES_BASELINE_UNIT_COST_CENTS = 8100
FRIES_CONTRACT_UNIT_COST_CENTS = 7500

CHICKEN_SKU = "PBC-TENDER-20"
CHICKEN_KEY = "CHICKEN-TENDER-CS20"
CHICKEN_PACK_SIZE = 20
CHICKEN_BASELINE_UNIT_COST_CENTS = 7200
CHICKEN_CONTRACT_UNIT_COST_CENTS = 6600

# ------------------------------------------------------------ rate cards ----
CARD_FROM = "2026-01-01"
CARD_TO = "2028-12-31"
FLAT_RATE_CENTS_PER_CASE = 150
TIER_BREAKS = [
    {"min_cases": 0, "rate_cents_per_case": 120},
    {"min_cases": 50, "rate_cents_per_case": 180},
    {"min_cases": 200, "rate_cents_per_case": 250},
]

# ------------------------------------------------------ batches and lines ----
JUNE_START = "2026-06-01"
JUNE_END = "2026-06-30"
JULY_START = "2026-07-01"
JULY_END = "2026-07-31"
JUNE_BATCH_REFERENCE = "METRO-2026-06"
JULY_BATCH_REFERENCE = "METRO-2026-07"

BEEF_DISTRIBUTOR_SKU = "MF-88120"
BEEF_DESCRIPTION = "Beef patty 4oz 40ct case"
FRIES_DISTRIBUTOR_SKU = "MF-71004"
FRIES_DESCRIPTION = "Shoestring fries 30lb"
CHICKEN_DISTRIBUTOR_SKU = "MF-44210"
CHICKEN_DESCRIPTION = "Chicken tenders 20lb"

INVOICE_UNIT_COST_CENTS = 9140
LINE_A_CASES = 30
LINE_A_BASE_COST_CENTS = 8533
LINE_A_INVOICE_DATE = "2026-06-05"
LINE_B_CASES = 40
LINE_B_BASE_COST_CENTS = 8540
LINE_B_INVOICE_DATE = "2026-06-18"
