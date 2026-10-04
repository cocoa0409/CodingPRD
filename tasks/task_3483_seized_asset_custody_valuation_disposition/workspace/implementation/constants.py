"""All PRD/SCAFFOLD-pinned constants for the Seized Asset Custody API.

Every named constant referenced anywhere in the implementation is defined
exactly once here (PRD §3 and SCAFFOLD §1.3 are the authorities).
"""

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
ROLE_CASE_AGENT = "CaseAgent"
ROLE_COURT_OFFICIAL = "CourtOfficial"
ROLE_ASSET_CUSTODIAN = "AssetCustodian"
ROLE_APPRAISER = "Appraiser"
ROLE_ASSET_MANAGER = "AssetManager"
ROLE_AUCTION_COORDINATOR = "AuctionCoordinator"
ROLE_FUND_ADMINISTRATOR = "FundAdministrator"
ROLE_CLAIMANT = "Claimant"
ROLE_SYSTEM_OPERATOR = "SystemOperator"

ROLES = (
    ROLE_CASE_AGENT,
    ROLE_COURT_OFFICIAL,
    ROLE_ASSET_CUSTODIAN,
    ROLE_APPRAISER,
    ROLE_ASSET_MANAGER,
    ROLE_AUCTION_COORDINATOR,
    ROLE_FUND_ADMINISTRATOR,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_OPERATOR,
)

# Every role except SystemOperator ("all business roles" in PRD §4).
BUSINESS_ROLES = tuple(r for r in ROLES if r != ROLE_SYSTEM_OPERATOR)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ---------------------------------------------------------------------------
# Enum domains
# ---------------------------------------------------------------------------
FORFEITURE_TYPES = ("CIVIL", "CRIMINAL", "ADMINISTRATIVE")

ASSET_TYPES = (
    "REAL_PROPERTY",
    "BUSINESS",
    "VEHICLE",
    "VESSEL",
    "AIRCRAFT",
    "PERSONAL_PROPERTY",
    "FINANCIAL_INSTRUMENT",
)

CONDITION_GRADES = ("EXCELLENT", "GOOD", "FAIR", "POOR", "SALVAGE")

LOCATION_KINDS = ("STORAGE", "MAINTENANCE_SHOP", "CLAIMANT_PREMISES", "OTHER")

VALUATION_METHODS = (
    "CERTIFIED_APPRAISAL",
    "MARKET_COMPARABLE",
    "BLUE_BOOK",
    "INCOME_APPROACH",
)

ENTRY_KINDS = ("COST", "REVENUE_OFFSET", "REVERSAL")

# expense_type domain for the ledger; STORAGE_ACCRUAL is system-reserved.
EXPENSE_TYPES_MANUAL = (
    "STORAGE",
    "MAINTENANCE",
    "MANAGEMENT_FEE",
    "INSURANCE",
    "SECURITY",
    "UTILITIES",
)
EXPENSE_TYPE_STORAGE_ACCRUAL = "STORAGE_ACCRUAL"
EXPENSE_TYPES_ALL = EXPENSE_TYPES_MANUAL + (EXPENSE_TYPE_STORAGE_ACCRUAL,)

TPI_KINDS = (
    "LIEN_MORTGAGE",
    "LIEN_TAX",
    "LIEN_JUDGMENT",
    "LIEN_MECHANIC",
    "INNOCENT_OWNER",
)
LIEN_KINDS = ("LIEN_MORTGAGE", "LIEN_TAX", "LIEN_JUDGMENT", "LIEN_MECHANIC")
KIND_INNOCENT_OWNER = "INNOCENT_OWNER"

SALE_METHODS = ("PUBLIC_AUCTION", "CONTRACTED_SELLER")

USAGE_RESTRICTIONS = ("OVERTIME", "TRAINING", "EQUIPMENT", "COMMUNITY_PROGRAM")

DECISIONS = ("RETAIN", "SELL")
VALUATION_OUTCOMES = ("ACCEPT", "REJECT")
ISR_OUTCOMES = ("APPROVE", "DENY")
TPI_OUTCOMES = ("VERIFY", "GRANT", "DENY")

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3 / PRD §3)
# ---------------------------------------------------------------------------
# condition_adjusted_valuation
CAPITALIZATION_BPS = 3300
CONDITION_FACTOR_BPS = {
    "EXCELLENT": 10000,
    "GOOD": 9000,
    "FAIR": 7500,
    "POOR": 5000,
    "SALVAGE": 2500,
}

# retention_value_estimate / interlocutory_eligibility / monthly accrual
PROVISIONAL_PROJECTION_MONTHS = 6
ISR_PROJECTION_MONTHS = 3
MONTHLY_CARRYING_COST_CENTS = {
    "REAL_PROPERTY": 150000,
    "BUSINESS": 400000,
    "VEHICLE": 25000,
    "VESSEL": 60000,
    "AIRCRAFT": 120000,
    "PERSONAL_PROPERTY": 8000,
    "FINANCIAL_INSTRUMENT": 2000,
}
RETENTION_VALUE_FLOOR_CENTS = 500000
INTERLOCUTORY_RATIO_THRESHOLD_PCT = 30

# auction_fee_schedule (tiered marginal, per-bracket RHU then summed)
TIER1_CAP_CENTS = 1000000
TIER1_BPS = 1000
TIER2_CAP_CENTS = 4000000
TIER2_BPS = 700
TIER3_BPS = 400

# depreciation_on_return
DEPRECIATION_PER_GRADE_STEP_BPS = 800
DEPRECIATION_PER_MONTH_BPS = 50
DEPRECIATION_CAP_BPS = 6000
GRADE_RANK = {"EXCELLENT": 5, "GOOD": 4, "FAIR": 3, "POOR": 2, "SALVAGE": 1}

# Misc pinned thresholds
DISPUTE_WINDOW_DAYS = 30
APPEAL_LIMIT = 1
EQUITABLE_SHARE_MIN_CENTS = 10000

# Waterfall payee marker for the cost-reimbursement bucket.
COST_REIMBURSEMENT_PAYEE = "CASE_COST_REIMBURSEMENT"

# Logical clock startup default (PRD §2.4) — exactly 2026-09-01T00:00:00Z.
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
