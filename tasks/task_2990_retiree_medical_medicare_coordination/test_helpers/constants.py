"""Business constants, enum vocabularies and endpoint paths from the PRD.

Every literal here is copied from the PRD: the role list (PRD 2.1), the
pagination rules (PRD 2.3), the logical-clock default (PRD 2.4), the named
calculation constants (PRD 3.2, 3.3, 3.6, 3.7, 3.8, 3.9) and the enum
vocabularies declared on the nine entities (PRD 2.4 / 3.x).
"""

# --------------------------------------------------------------------------- #
# Roles (PRD 2.1). Seven operator roles are opaque; Retiree is entity-backed:
# its X-User-ID is the id of the Retiree row it acts for.
# --------------------------------------------------------------------------- #
ROLE_BENEFITS_ADMIN = "BenefitsAdmin"
ROLE_ELIGIBILITY_ANALYST = "EligibilityAnalyst"
ROLE_ENROLLMENT_COUNSELOR = "EnrollmentCounselor"
ROLE_HRA_ADMINISTRATOR = "HraAdministrator"
ROLE_BILLING_CLERK = "BillingClerk"
ROLE_ACTUARY = "Actuary"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_RETIREE = "Retiree"

ALL_ROLES = [
    ROLE_BENEFITS_ADMIN,
    ROLE_ELIGIBILITY_ANALYST,
    ROLE_ENROLLMENT_COUNSELOR,
    ROLE_HRA_ADMINISTRATOR,
    ROLE_BILLING_CLERK,
    ROLE_ACTUARY,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_RETIREE,
]

OPERATOR_ROLES = [r for r in ALL_ROLES if r != ROLE_RETIREE]

# --------------------------------------------------------------------------- #
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------- #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------- #
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------- #
# Named calculation constants (PRD 3.2, 3.3, 3.6, 3.7, 3.8, 3.9)
# --------------------------------------------------------------------------- #
GRANDFATHER_CUTOFF_A = "1993-01-01"
GRANDFATHER_CUTOFF_B = "2005-01-01"
RULE_OF_75_POINTS = 75
GRANDFATHERED_MIN_AGE = 55
GRANDFATHERED_MIN_SERVICE_YEARS = 10

ESRD_COORDINATION_MONTHS = 30
WORKING_AGED_EMPLOYER_THRESHOLD = 20
DISABILITY_EMPLOYER_THRESHOLD = 100

DENTAL_VISION_REIMBURSEMENT_BPS = 5000
QUALIFIED_MEDICAL_PER_CLAIM_CAP_CENTS = 50000

ADMIN_FEE_BPS = 350
EMPLOYER_SUBSIDY_BPS_BY_GROUP = {
    "GRANDFATHERED_A": 8000,
    "TRANSITION_B": 6000,
    "STANDARD_C": 4000,
}
LONG_SERVICE_BONUS_YEARS = 25
LONG_SERVICE_BONUS_BPS = 1000
MAX_EMPLOYER_SUBSIDY_BPS = 10000
PREMIUM_DUE_DAYS = 30

STANDARD_PART_D_GROSS_VALUE_BPS = 10000
STANDARD_PART_D_NET_VALUE_BPS = 7450

FULL_ELIGIBILITY_SERVICE_YEARS_BY_GROUP = {
    "GRANDFATHERED_A": 15,
    "TRANSITION_B": 20,
    "STANDARD_C": 25,
}
ASSUMED_POST_ELIGIBILITY_SERVICE_YEARS = 5

LIFE_EVENT_WINDOW_DAYS = 31
LAPSE_THRESHOLD_PERIODS = 3

# --------------------------------------------------------------------------- #
# Enum vocabularies (PRD 2.4 / 3.x entity field declarations)
# --------------------------------------------------------------------------- #
PLAN_YEAR_STATUSES = ["DRAFT", "OPEN", "CLOSED", "ARCHIVED"]
LIABILITY_METHODS = ["PROJECTED_UNIT_CREDIT", "ATTRIBUTION_TO_FULL_ELIGIBILITY"]

ELIGIBILITY_STATUSES = ["UNDETERMINED", "ELIGIBLE", "INELIGIBLE"]
MEDICARE_STATUSES = [
    "PRE_MEDICARE",
    "MEDICARE_ELIGIBLE_NOT_ENROLLED",
    "MEDICARE_ENROLLED",
    "MEDICARE_WAIVED",
]
GRANDFATHER_GROUPS = ["GRANDFATHERED_A", "TRANSITION_B", "STANDARD_C"]

COVERAGE_CLASSES = [
    "PRE_MEDICARE_GROUP",
    "MEDICARE_GROUP_WRAP",
    "INDIVIDUAL_EXCHANGE_HRA",
]
SUBSIDY_VEHICLES = ["RDS", "EGWP", "NONE"]
PLAN_OPTION_STATUSES = ["DRAFT", "ACTIVE", "CLOSED_TO_NEW", "RETIRED"]
SUBSIDY_CERTIFICATION_STATUSES = ["NOT_STARTED", "ATTESTED", "CERTIFIED", "REJECTED"]
PENDING_CHANGE_TYPES = ["PREMIUM_INCREASE", "PLAN_TERMINATION"]

RULE_SET_CODES = [
    "RULE_OF_75_GRANDFATHERED",
    "AGE_60_SERVICE_15",
    "AGE_65_SERVICE_10",
]
DETERMINATION_OUTCOMES = ["ELIGIBLE", "INELIGIBLE"]
DETERMINATION_STATUSES = ["DRAFT", "CERTIFIED", "UNDER_APPEAL", "SUPERSEDED"]
APPEAL_DECISIONS = ["UPHOLD", "REVERSE"]

ELECTION_EVENT_TYPES = [
    "ANNUAL_OPEN",
    "MEDICARE_ENTITLEMENT",
    "LOSS_OF_OTHER_COVERAGE",
    "MARRIAGE",
    "DEPENDENT_DEATH",
]
LIFE_EVENT_TYPES = [
    "MEDICARE_ENTITLEMENT",
    "LOSS_OF_OTHER_COVERAGE",
    "MARRIAGE",
    "DEPENDENT_DEATH",
]
ELECTION_STATUSES = ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"]
ELECTION_DENIAL_REASON_CODES = ["COUNSELOR_DENIAL", "PLAN_CLOSED"]

COVERAGE_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
HEADCOUNT_COVERAGE_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED"]
BILLING_STATUSES = ["CURRENT", "DELINQUENT", "LAPSED", "REINSTATED"]
PAYER_ORDERS = ["GROUP_PRIMARY", "GROUP_PRIMARY_WORKING_AGED", "MEDICARE_PRIMARY"]
MSP_BASIS_CODES = [
    "NO_OTHER_COVERAGE",
    "ESRD_WITHIN_COORDINATION",
    "ESRD_AFTER_COORDINATION",
    "WORKING_AGED_LARGE_EMPLOYER",
    "WORKING_AGED_SMALL_EMPLOYER",
    "DISABILITY_LARGE_EMPLOYER",
    "DISABILITY_SMALL_EMPLOYER",
    "MEDICARE_PRIMARY_RETIREE_COVERAGE",
]

HRA_ACCOUNT_STATUSES = ["OPEN", "FROZEN", "CLOSED"]
EXPENSE_CATEGORIES = [
    "MEDICARE_PART_B_PREMIUM",
    "MEDIGAP_PREMIUM",
    "PART_D_PREMIUM",
    "EXCHANGE_PREMIUM",
    "DENTAL_VISION_PREMIUM",
    "QUALIFIED_MEDICAL",
]
CLAIM_STATUSES = [
    "SUBMITTED",
    "PENDING_SUBSTANTIATION",
    "APPROVED",
    "PAID",
    "DENIED",
    "REVERSED",
]
CLAIM_DENIAL_REASON_CODES = [
    "UNSUBSTANTIATED",
    "INELIGIBLE_CATEGORY",
    "ACCOUNT_NOT_OPEN",
    "REVIEWER_DENIAL",
]

INVOICE_STATUSES = ["ISSUED", "PARTIALLY_PAID", "PAID", "PAST_DUE", "WRITTEN_OFF"]

# The five HRA ledger buckets whose sum must always equal funded_cents
# (PRD 2.10 HRA ledger conservation).
HRA_LEDGER_BUCKETS = [
    "available_balance_cents",
    "pending_hold_cents",
    "substantiated_paid_cents",
    "premium_offset_cents",
    "forfeited_cents",
]

# --------------------------------------------------------------------------- #
# Endpoint path prefixes (PRD 4)
# --------------------------------------------------------------------------- #
BASE = "/retiree-benefits"
PATH_PLAN_YEARS = f"{BASE}/plan-years"
PATH_RETIREES = f"{BASE}/retirees"
PATH_PLAN_OPTIONS = f"{BASE}/plan-options"
PATH_DETERMINATIONS = f"{BASE}/eligibility-determinations"
PATH_ELECTION_EVENTS = f"{BASE}/election-events"
PATH_ENROLLMENTS = f"{BASE}/enrollments"
PATH_HRA_ACCOUNTS = f"{BASE}/hra-accounts"
PATH_CLAIMS = f"{BASE}/reimbursement-claims"
PATH_INVOICES = f"{BASE}/premium-invoices"
PATH_CLOCK = "/_clock/set_current_utc"
PATH_DAILY_RUN = "/_ops/daily-run"

# Fields every entity carries (PRD 2.4)
COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
