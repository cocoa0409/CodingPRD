"""All named constants with exactly their PRD / SCAFFOLD values."""

# Logical clock startup default (PRD 2.4): exactly 2026-09-01T00:00:00Z.
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# Declared roles (PRD 2.1).
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PROGRAM_OFFICER = "ProgramOfficer"
ROLE_HOST_COMMISSION = "HostCommission"
ROLE_NATIONAL_REVIEWER = "NationalReviewer"
ROLE_CAMPUS_REVIEWER = "CampusReviewer"
ROLE_APPLICANT = "Applicant"
ROLE_ANONYMOUS = "Anonymous"
ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_NATIONAL_REVIEWER,
    ROLE_CAMPUS_REVIEWER,
    ROLE_APPLICANT,
    ROLE_ANONYMOUS,
)
# Roles admitted by the generic GET endpoints (everyone except Anonymous).
READ_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_NATIONAL_REVIEWER,
    ROLE_CAMPUS_REVIEWER,
    ROLE_APPLICANT,
)

# Review quorums (PRD 3.3).
CAMPUS_QUORUM = 2
NATIONAL_QUORUM = 2

# Weighted screening score constants (PRD 3.3). Decimal-valued as strings.
WEIGHT_FEASIBILITY = "0.40"
WEIGHT_COUNTRY_FIT = "0.35"
WEIGHT_LANGUAGE = "0.25"
RECOMMEND_SCORE_THRESHOLD = "70.00"
MIN_AVG_FEASIBILITY = "50"
LANGUAGE_GATE_PROFICIENT = "80"
LANGUAGE_GATE_BASIC = "60"

# Grant award terms (PRD 3.6).
DEPENDENT_CAP = 2
DEP_CAP_PCT_OF_BASE = "0.25"

# Early termination reconciliation (PRD 3.8).
DAYS_PER_MONTH = 30

# Residency accrual (PRD 3.9).
RESIDENCY_REQUIRED_DAYS = 730

# Report obligations (PRD 3.7 / 3.9).
INTERIM_REPORT_DUE_MONTHS = 4
FINAL_REPORT_DUE_DAYS = 30
MAX_COMPLIANCE_STRIKES = 2

# Alumni engagement index (PRD 3.9).
ENGAGEMENT_BASE_POINTS = 50
REPORT_ACCEPT_POINTS = 10
STRIKE_PENALTY_POINTS = 20

# Placement negotiation cap (PRD 3.5).
MAX_PLACEMENT_ROUNDS = 3

# Slot-consuming application states (calculations.slot_accounting).
SLOT_CONSUMING_STATES = ("SELECTED", "PLACEMENT", "GRANT_PENDING", "AWARDED")

# Duplicate-application guard set (PRD 3.2): submitted-or-later non-terminal.
ACTIVE_APPLICATION_STATES = (
    "CAMPUS_REVIEW",
    "NATIONAL_SCREENING",
    "HOST_REVIEW",
    "SELECTED",
    "ALTERNATE",
    "PLACEMENT",
    "GRANT_PENDING",
    "AWARDED",
)
