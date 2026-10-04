"""Static constants for the Integrated Payer-Provider Budgeting API.

Every constant here is copied from PRD.md section 3 / SCAFFOLD.yaml section 1.3.
"""

from decimal import Decimal

# --- Roles (PRD 2.1) -------------------------------------------------------
ROLE_REGIONAL_FINANCE_OFFICER = "RegionalFinanceOfficer"
ROLE_UTILIZATION_REVIEWER = "UtilizationReviewer"
ROLE_ACCESS_SCHEDULER = "AccessScheduler"
ROLE_QUALITY_REVIEW_BOARD = "QualityReviewBoard"
ROLE_BUDGET_APPROPRIATIONS_COMMITTEE = "BudgetAppropriationsCommittee"
ROLE_CARE_TEAM_MEMBER = "CareTeamMember"
ROLE_PROVIDER = "Provider"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_REGIONAL_FINANCE_OFFICER,
    ROLE_UTILIZATION_REVIEWER,
    ROLE_ACCESS_SCHEDULER,
    ROLE_QUALITY_REVIEW_BOARD,
    ROLE_BUDGET_APPROPRIATIONS_COMMITTEE,
    ROLE_CARE_TEAM_MEMBER,
    ROLE_PROVIDER,
    ROLE_PLATFORM_ADMIN,
)

# --- Capitation rule (PRD 3.1) --------------------------------------------
BASE_RATE_CENTS = {
    "COMMERCIAL_HMO": 42000,
    "MEDICARE_ADVANTAGE": 95000,
    "MEDICAID_MANAGED": 28000,
    "DUAL_ELIGIBLE": 118000,
}
CAPITATION_FLOOR_MULTIPLIER = Decimal("0.5")
CAPITATION_CEIL_MULTIPLIER = Decimal("2.5")

# --- Provider compensation (PRD 3.2) --------------------------------------
PANEL_RATE_CENTS = {
    "PRIMARY_CARE": 900,
    "CARDIOLOGY": 1400,
    "ORTHOPEDICS": 1500,
    "ONCOLOGY": 1800,
    "RADIOLOGY": 1100,
    "BEHAVIORAL_HEALTH": 1000,
}
QUALITY_BONUS_THRESHOLD = Decimal("85")
QUALITY_BONUS_RATE = Decimal("0.10")

# --- Regional operating budget (PRD 3.7, 3.8) -----------------------------
FTE_COST_CENTS = 1250000
MARGIN_FREEZE_FLOOR_CENTS = 500000000

# --- Capacity supply (PRD 3.3) --------------------------------------------
PANEL_TARGET_MEMBERS_PER_SLOT = Decimal("1.5")

# --- Quality composite weighting (PRD 3.10) -------------------------------
WEIGHT_BY_METRIC = {
    "ACCESS_WAIT_DAYS": Decimal("0.40"),
    "QUALITY_COMPOSITE": Decimal("0.30"),
    "MEMBER_SATISFACTION": Decimal("0.20"),
    "PANEL_AVAILABILITY": Decimal("0.10"),
}

# --- Outside services liability (PRD 3.6) ---------------------------------
ANNUAL_DEDUCTIBLE_CENTS = 150000
COINSURANCE_RATE = Decimal("0.20")
OUT_OF_POCKET_CAP_CENTS = 600000
EMERGENCY_PAY_RATE = Decimal("0.75")
VENDOR_ALLOWABLE_PCT = {"KP Affiliate": Decimal("0.80")}
DEFAULT_VENDOR_ALLOWABLE_PCT = Decimal("0.70")

# --- Referential integration settlement (PRD 3.11) ------------------------
INTERIM_CLAIM_THRESHOLD = 40
INTERIM_HIGH_MULTIPLIER = Decimal("1.5")
INTEGRATION_CREDIT_RATE = {
    "CAPITATED": Decimal("0.12"),
    "SHARED_SAVINGS": Decimal("0.20"),
    "BUNDLED": Decimal("0.08"),
    "NOT_AT_RISK": Decimal("0.0"),
}

# --- Referral rules (PRD 3.5) ---------------------------------------------
REFERRAL_EXPIRY_DAYS = 90
APPEAL_ROUNDS_MAX = 2
# REFERRAL_TRIAGE_WINDOW_DAYS and EXTERNAL_CONTRACT_MAX are named in the error
# catalogue but never given a numeric value in PRD.md / SCAFFOLD.yaml; the
# values below are the implementation's chosen readings.
REFERRAL_TRIAGE_WINDOW_DAYS = 30
EXTERNAL_CONTRACT_MAX = 3

# --- Logical clock (PRD 2.11) ---------------------------------------------
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# --- Pagination (PRD 2.3) -------------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0