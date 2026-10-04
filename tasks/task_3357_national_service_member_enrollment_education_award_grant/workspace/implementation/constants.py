"""Domain constants. Every value here is pinned by PRD.md / SCAFFOLD.yaml."""
from decimal import Decimal

# --- Term table (PRD 2.7) -----------------------------------------------------
TERM_CATEGORIES = [
    "FULL_TIME",
    "HALF_TIME",
    "REDUCED_HALF_TIME",
    "QUARTER_TIME",
    "MINIMUM_TIME",
    "ABBREVIATED_TIME",
]

TERM_MINUTES = {
    "FULL_TIME": 102000,
    "HALF_TIME": 54000,
    "REDUCED_HALF_TIME": 40500,
    "QUARTER_TIME": 27000,
    "MINIMUM_TIME": 18000,
    "ABBREVIATED_TIME": 6000,
}

AWARD_CENTS = {
    "FULL_TIME": 739500,
    "HALF_TIME": 391500,
    "REDUCED_HALF_TIME": 293625,
    "QUARTER_TIME": 195750,
    "MINIMUM_TIME": 130500,
    "ABBREVIATED_TIME": 43500,
}

ALLOWANCE_TOTAL_CENTS = {
    "FULL_TIME": 2200000,
    "HALF_TIME": 1100000,
    "REDUCED_HALF_TIME": 825000,
    "QUARTER_TIME": 550000,
    "MINIMUM_TIME": 366700,
    "ABBREVIATED_TIME": 122200,
}

# One member-service year = one full-time term.
MSY_MINUTES = 102000

# --- Cost per MSY cap (PRD 3.2) ------------------------------------------------
COST_PER_MSY_CAP_CENTS = Decimal("2300000.00")

# --- Match rules (PRD 3.2/3.3) --------------------------------------------------
MATCH_RATE_CASH = Decimal("1.00")
MATCH_RATE_IN_KIND = Decimal("0.80")
MATCH_MIN_NUMERATOR = 6        # allowable * 25 >= federal * 6
MATCH_MIN_DENOMINATOR = 25

# --- Allowance gates (PRD 3.6) ---------------------------------------------------
ALLOWANCE_PERIOD_MAX_CENTS = 100000

# --- Education award (PRD 3.7) ----------------------------------------------------
PRORATION_FLOOR_PCT = 15
AWARD_USE_DEADLINE_YEARS = 7

# --- Fundraising cap (PRD 3.5) -----------------------------------------------------
FUNDRAISING_CAP_PCT = 10

# --- Compliance (PRD 3.8) -----------------------------------------------------------
VISIT_BUFFER_DAYS = 30
DUE_DAYS_MIN = 14
DUE_DAYS_MAX = 90
ESCALATION_REASON = "ESCALATED_FINDING_OVERDUE"

# --- Enrollment safety (PRD 3.4) -----------------------------------------------------
MIN_MEMBER_AGE_YEARS = 17

# --- Hour entries (PRD 3.5) -----------------------------------------------------------
MINUTES_MIN = 1
MINUTES_MAX = 48000

# --- Slot refill -----------------------------------------------------------------------
SLOT_MAX_FILL_COUNT = 2

# --- Enumerations ------------------------------------------------------------------------
ORG_TYPES = ["NONPROFIT", "PUBLIC_AGENCY", "INSTITUTION_OF_HIGHER_ED", "TRIBAL"]
CITIZENSHIP_STATUSES = ["US_CITIZEN", "US_NATIONAL", "LAWFUL_PERMANENT_RESIDENT"]
ACTIVITY_CODES = [
    "DIRECT_SERVICE",
    "CAPACITY_BUILDING",
    "TRAINING",
    "FUNDRAISING",
    "PROSELYTIZING",
    "PARTISAN_LOBBYING",
]
PROHIBITED_ACTIVITIES = ["PROSELYTIZING", "PARTISAN_LOBBYING"]
MATCH_CATEGORIES = ["CASH", "IN_KIND"]
VISIT_TYPES = ["SITE_VISIT", "FILE_REVIEW"]
SEVERITIES = ["LOW", "HIGH"]
MEASURE_CODES = ["MSY_OUTPUT", "BENEFICIARY_OUTCOME", "COMMUNITY_OUTCOME"]
USE_TYPES = ["TUITION", "QUALIFIED_LOAN"]
CHECK_COMPONENTS = ["NSOPR", "STATE_REPOSITORY", "FBI_FINGERPRINT"]
CHECK_RESULTS = ["CLEAR", "FLAGGED"]
EXIT_REASONS = ["SUCCESSFUL", "COMPELLING_CIRCUMSTANCE", "FOR_CAUSE"]
GRIEVANCE_OUTCOMES = ["UPHELD", "DISMISSED"]
REVIEW_DECISIONS = ["ACCEPT", "RETURN"]
USE_DECISIONS = ["APPROVE", "DENY"]
FINDING_DECISIONS = ["APPROVE", "REJECT"]

ROLES = [
    "Anonymous",
    "CNCSProgramOfficer",
    "GranteeStaff",
    "Member",
    "ComplianceOfficer",
    "TrustAdministrator",
]

# Criminal check component name -> entity field.
COMPONENT_FIELD = {
    "NSOPR": "nsopr_status",
    "STATE_REPOSITORY": "state_status",
    "FBI_FINGERPRINT": "fbi_status",
}
