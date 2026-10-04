"""Single home for every named constant the PRD states in prose.

No other module is allowed to invent its own value for any of these names.
All monetary values are integer cents; all rates are percent decimals.
"""

from decimal import Decimal

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
API_PREFIX = "/wholesale-channel"

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.10 / 2.6)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
# Fixture convention only - carried for reproducibility, read by no rule.
EARLY_FUNDING_CUTOFF_UTC = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Financial strength scoring (PRD 3.2)
# ---------------------------------------------------------------------------
NET_WORTH_TARGET_CENTS = 100_000_000
LIQUIDITY_TARGET_CENTS = 40_000_000
LEVERAGE_CAP_RATIO = Decimal("3.0")
EXPERIENCE_TARGET_YEARS = 5
NET_WORTH_FLOOR_CENTS = 25_000_000
ATTAINMENT_MEETS_RATIO = Decimal("1.0")
ATTAINMENT_NEAR_RATIO = Decimal("0.75")

SCORE_MIN = Decimal("0.00")
SCORE_MAX = Decimal("100.00")

BAND_MEETS = "MEETS_EXPECTATION"
BAND_NEAR = "NEAR_EXPECTATION"
BAND_BELOW = "BELOW_EXPECTATION"
BAND_SCORES = {BAND_MEETS: 100, BAND_NEAR: 75, BAND_BELOW: 40}

# ---------------------------------------------------------------------------
# Tier ladder (PRD 3.2)
# ---------------------------------------------------------------------------
TIER_1_MIN_SCORE = Decimal("85.00")
TIER_2_MIN_SCORE = Decimal("60.00")
TIER_3_MIN_SCORE = Decimal("40.00")

TIER_UNRATED = "UNRATED"
TIER_1 = "TIER_1"
TIER_2 = "TIER_2"
TIER_3 = "TIER_3"

# ---------------------------------------------------------------------------
# Pricing dimensions (PRD 3.5)
# ---------------------------------------------------------------------------
CREDIT_ADJUSTMENTS = [
    Decimal("-0.125"),  # 760 and above
    Decimal("-0.050"),  # 740 <= fico < 760
    Decimal("0.000"),   # 720 <= fico < 740
    Decimal("0.125"),   # 700 <= fico < 720
    Decimal("0.250"),   # 680 <= fico < 700
    Decimal("0.500"),   # below 680
]

LTV_ADJUSTMENTS = [
    Decimal("0.000"),   # <= 0.60
    Decimal("0.050"),   # (0.60, 0.70]
    Decimal("0.125"),   # (0.70, 0.80]
    Decimal("0.250"),   # (0.80, 0.90]
    Decimal("0.375"),   # (0.90, 0.95]
    Decimal("0.500"),   # > 0.95
]

OCCUPANCY_ADJUSTMENTS = {
    "PRIMARY_RESIDENCE": Decimal("0.000"),
    "SECOND_HOME": Decimal("0.250"),
    "INVESTMENT": Decimal("0.500"),
}

PRODUCT_ADJUSTMENTS = {
    "CONVENTIONAL": Decimal("0.000"),
    "FHA": Decimal("0.125"),
    "VA": Decimal("-0.125"),
    "JUMBO": Decimal("0.375"),
    "USDA": Decimal("0.250"),
}

OCCUPANCY_TYPES = ["PRIMARY_RESIDENCE", "SECOND_HOME", "INVESTMENT"]
LOAN_PURPOSES = ["PURCHASE", "RATE_TERM_REFINANCE", "CASH_OUT_REFINANCE"]
PRODUCT_CODES = ["CONVENTIONAL", "FHA", "VA", "JUMBO", "USDA"]

LTV_BAND_COUNT = 6

# ---------------------------------------------------------------------------
# Lock surcharge (PRD 3.5)
# ---------------------------------------------------------------------------
LOCK_SURCHARGE_15D = Decimal("0.125")
LOCK_SURCHARGE_30D = Decimal("0.000")
LOCK_SURCHARGE_60D = Decimal("-0.125")
LOCK_BOUNDARY_SHORT_DAYS = 30
LOCK_BOUNDARY_LONG_DAYS = 60

# ---------------------------------------------------------------------------
# Base price grid (PRD 3.5) - rows keyed by rounded credit bucket, columns by
# the six ascending LTV bands.
# ---------------------------------------------------------------------------
PRICE_TABLE_ROWS = {
    "760+": [Decimal("-1.00"), Decimal("-0.75"), Decimal("-0.50"),
             Decimal("-0.25"), Decimal("0.00"), Decimal("0.25")],
    "740": [Decimal("-0.75"), Decimal("-0.50"), Decimal("-0.25"),
            Decimal("0.00"), Decimal("0.25"), Decimal("0.50")],
    "720": [Decimal("-0.50"), Decimal("-0.25"), Decimal("0.00"),
            Decimal("0.25"), Decimal("0.50"), Decimal("0.75")],
    "700": [Decimal("-0.25"), Decimal("0.00"), Decimal("0.25"),
            Decimal("0.50"), Decimal("0.75"), Decimal("1.00")],
    "680": [Decimal("0.00"), Decimal("0.25"), Decimal("0.50"),
            Decimal("0.75"), Decimal("1.00"), Decimal("1.25")],
    "660": [Decimal("0.25"), Decimal("0.50"), Decimal("0.75"),
            Decimal("1.00"), Decimal("1.25"), Decimal("1.50")],
    "<660": [Decimal("0.50"), Decimal("0.75"), Decimal("1.00"),
             Decimal("1.25"), Decimal("1.50"), Decimal("1.75")],
}

TIER_DISCOUNT = {
    "PLATINUM": Decimal("-0.25"),
    "GOLD": Decimal("-0.10"),
    "SILVER": Decimal("0.000"),
    "BRONZE": Decimal("0.25"),
}
PLATINUM_MAX_POINTS = Decimal("-0.50")
GOLD_MAX_POINTS = Decimal("0.00")
SILVER_MAX_POINTS = Decimal("0.50")

# ---------------------------------------------------------------------------
# Compensation (PRD 3.6)
# ---------------------------------------------------------------------------
LENDER_PAID_RATE_IMPACT = Decimal("0.250")
BORROWER_PAID_RATE_IMPACT = Decimal("-0.250")

ELECTION_LENDER_PAID = "LENDER_PAID"
ELECTION_BORROWER_PAID = "BORROWER_PAID"
ELECTION_UNDECIDED = "UNDECIDED"
ELECTION_VALUES = [ELECTION_LENDER_PAID, ELECTION_BORROWER_PAID, ELECTION_UNDECIDED]
PLAN_CODES = ["PLAN_A", "PLAN_B", "PLAN_C"]

# ---------------------------------------------------------------------------
# Quality control (PRD 3.9)
# ---------------------------------------------------------------------------
DEFECT_WEIGHTS = {
    "INCOME_DISCREPANCY": Decimal("8.00"),
    "UNDISCLOSED_LIABILITY": Decimal("5.00"),
    "APPRAISAL_DEVIATION": Decimal("6.00"),
    "TITLE_DEFECT": Decimal("7.00"),
    "LICENSE_DEFECT": Decimal("10.00"),
    "NON_DEFECT": Decimal("0.00"),
}
SEVERITY_MULTIPLIERS = {
    "MINOR": Decimal("0.50"),
    "MAJOR": Decimal("1.00"),
    "CRITICAL": Decimal("1.50"),
}
REPURCHASE_POINTS_THRESHOLD = Decimal("12.00")
REPURCHASE_WINDOW_DAYS = 30

TIER_MULTIPLIERS = [
    Decimal("1.00"),  # open_defect_tier == 0
    Decimal("1.25"),  # 1
    Decimal("1.50"),  # 2
    Decimal("2.00"),  # 3
    Decimal("2.50"),  # 4 or more
]

# ---------------------------------------------------------------------------
# Repurchase (PRD 3.9)
# ---------------------------------------------------------------------------
ORIGINATION_FEE_SHARE = Decimal("0.5")

# ---------------------------------------------------------------------------
# Exclusivity (PRD 3.4)
# ---------------------------------------------------------------------------
WARNED_AT_BREACHED_POLICIES = 1
RESTRICTED_AT_BREACHED_POLICIES = 2
BLOCKED_AT_BREACHED_POLICIES = 3

POLICY_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED", "VOIDED"]
RESTRICTION_SCOPES = ["LOAN_SUBMISSION", "RATE_LOCK", "ALL"]
OP_LOAN_SUBMISSION = "LOAN_SUBMISSION"
OP_RATE_LOCK = "RATE_LOCK"

# ---------------------------------------------------------------------------
# Turn-time commitments (PRD 2.6)
# ---------------------------------------------------------------------------
UNDERWRITING_TURN_DAYS = 10
CLOSING_TURN_DAYS = 7
UNDERWRITING_EXTENSION_DAYS = 5
OPEN_DEFECT_DEADLINE_DAYS = 3

NEAR_DEADLINE_WINDOW_DAYS = 3

# ---------------------------------------------------------------------------
# Broker standing (PRD 2.4)
# ---------------------------------------------------------------------------
QUALITY_SUSPENSION_THRESHOLD = Decimal("40.00")
DEFECT_SUSPENSION_TIER = 5
FINANCIAL_SUSPENSION_THRESHOLD = Decimal("40.00")
REINSTATEMENT_QUALITY_THRESHOLD = Decimal("60.00")
REINSTATEMENT_DEFECT_TIER = 2

SUSPENSION_REASON_QUALITY = "QUALITY"
SUSPENSION_REASON_DEFECTS = "DEFECTS"
SUSPENSION_REASON_FINANCIAL = "FINANCIAL"
SUSPENSION_REASON_EXCLUSIVITY = "EXCLUSIVITY"

# ---------------------------------------------------------------------------
# Status universes
# ---------------------------------------------------------------------------
BROKER_STATUSES = ["SUBMITTED", "APPROVED", "SUSPENDED", "TERMINATED"]
LICENSE_STATUSES = ["ACTIVE", "EXPIRED", "REVOKED"]
LICENSE_TYPES = ["MORTGAGE_BROKER", "MORTGAGE_LENDER", "DUAL_AUTHORITY"]
REVIEW_STATUSES = ["PENDING", "PASSED", "FAILED"]
ELIGIBILITY_STATUSES = ["PENDING", "APPROVED", "REVOKED"]
SHEET_STATUSES = ["PUBLISHED", "SUPERSEDED", "RETIRED"]
LOAN_STATUSES = [
    "SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL", "SUSPENDED_REVIEW",
    "CLEAR_TO_CLOSE", "FUNDED", "DENIED", "WITHDRAWN", "REPURCHASED",
]
LOAN_ACTIVE_STATUSES = [
    "SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL",
    "SUSPENDED_REVIEW", "CLEAR_TO_CLOSE",
]
LOAN_COMMITMENT_STATUSES = ["SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL"]
LOAN_WITHDRAWABLE_STATUSES = ["SUBMITTED", "UNDERWRITING", "CONDITIONAL_APPROVAL"]
LOAN_QC_REVIEWABLE_STATUSES = [
    "FUNDED", "CLEAR_TO_CLOSE", "REPURCHASED", "CONDITIONAL_APPROVAL",
]
DECISION_TYPES = ["APPROVED", "CONDITIONAL", "SUSPENDED", "DENIED"]
ESCALATION_STAGES = ["UNDERWRITING", "CLOSING"]
ESCALATION_STATUSES = ["OPEN", "RESOLVED"]
QC_OUTCOMES = ["PENDING", "CLEAR", "DEFECT"]
QC_REMEDIATION_STATUSES = ["NONE", "OPEN", "REMEDIATED", "VOIDED"]

EXCLUSIVITY_CLEAR = "CLEAR"
EXCLUSIVITY_WARNED = "WARNED"
EXCLUSIVITY_RESTRICTED = "RESTRICTED"
EXCLUSIVITY_BLOCKED = "BLOCKED"

LICENSE_REVOKED_REASON = "LICENSE_REVOKED"
QC_DEFECT_HOLD_NOTE = "QC_DEFECT_HOLD"

CLOSING_PATH_ESCALATION = "ESCALATION_PATH"
CLOSING_PATH_STANDARD = "STANDARD_PATH"

# ---------------------------------------------------------------------------
# RBAC (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_CHANNEL_MANAGER = "ChannelManager"
ROLE_UNDERWRITER = "Underwriter"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_QC_ANALYST = "QualityControlAnalyst"
ROLE_BROKER_USER = "BrokerUser"
ROLE_ANY = "Any"

DECLARED_ROLES = [
    ROLE_PLATFORM_ADMIN, ROLE_CHANNEL_MANAGER, ROLE_UNDERWRITER,
    ROLE_COMPLIANCE_OFFICER, ROLE_QC_ANALYST, ROLE_BROKER_USER, ROLE_ANY,
]

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
TS_FORMAT_SUFFIX = "Z"