"""Domain constants for the Meeting Venue Sourcing & RFP API test suite.

Every value here is stated in the PRD: role names, enum members, the numeric
constants of the pricing, rebate, deposit and scoring formulas, and the API's
default logical-clock instant.
"""

# --- Roles ---------------------------------------------------------------
ROLE_SOURCING_MANAGER = "SourcingManager"
ROLE_VENUE_REP = "VenueRep"
ROLE_CONTRACT_APPROVER = "ContractApprover"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = [
    ROLE_SOURCING_MANAGER,
    ROLE_VENUE_REP,
    ROLE_CONTRACT_APPROVER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PROGRAM_ADMIN,
]

# --- Enumerations --------------------------------------------------------
DESTINATION_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
PROGRAM_TYPES = [
    "BOARD_MEETING",
    "SALES_KICKOFF",
    "TRAINING",
    "USER_CONFERENCE",
    "INCENTIVE",
]
PREFERRED_SUPPLIER_STATUSES = ["PREFERRED", "CONDITIONAL", "NONE", "SUSPENDED"]
PROGRAM_STATUS_SNAPSHOTS = ["IN_PROGRAM", "OUT_OF_PROGRAM"]

EVENT_STATUSES = [
    "DRAFT",
    "REQUIREMENTS_LOCKED",
    "SOURCING",
    "BID_REVIEW",
    "AWARDED",
    "CONTRACTED",
    "COMPLETED",
    "CANCELLED",
]
SHORTLIST_ENTRY_STATUSES = [
    "CANDIDATE",
    "SHORTLISTED",
    "INSPECTION_SCHEDULED",
    "INSPECTED",
    "RFP_ISSUED",
    "AWARDED",
    "ELIMINATED",
]
INSPECTION_STATUSES = ["PLANNED", "COMPLETED", "CANCELLED", "NO_SHOW"]
RFP_STATUSES = ["DRAFT", "ISSUED", "CLOSED"]
PROPOSAL_STATUSES = [
    "INVITED",
    "SUBMITTED",
    "UNDER_REVIEW",
    "COUNTERED",
    "REVISED",
    "AWARDED",
    "REJECTED",
    "DECLINED",
    "WITHDRAWN",
    "EXPIRED",
]
APPROVAL_STATES = ["PENDING_ROUTING", "IN_APPROVAL", "APPROVED", "REJECTED", "CANCELLED"]
SIGNATURE_STATES = [
    "UNSIGNED",
    "PLANNER_SIGNED",
    "COUNTERSIGNED",
    "EXECUTED",
    "TERMINATED",
    "VOIDED",
]
APPROVAL_DECISIONS = ["PENDING", "APPROVED", "REJECTED", "SKIPPED"]
APPROVAL_LEVELS = ["PROGRAM_COMPLIANCE", "MANAGER", "VP", "LEGAL"]
INSTALLMENT_STATUSES = ["SCHEDULED", "PAID", "CANCELLED"]

RATE_TYPES = ["NET", "GROSS"]
FORCE_MAJEURE_SCOPES = ["NARROW", "STANDARD", "BROAD"]
STANDARD_RESPONSE_VERSIONS = ["V1", "V2"]
EVALUATION_BASES = ["CONTRACTED_BASIS", "ACTUALIZED_BASIS"]
TERM_CATEGORIES = [
    "RATE",
    "CONCESSION",
    "ATTRITION",
    "CANCELLATION",
    "FORCE_MAJEURE",
    "REBOOKING_CREDIT",
]
NUMERIC_TERM_CATEGORIES = ["RATE", "CONCESSION", "ATTRITION", "REBOOKING_CREDIT"]
TEXT_TERM_CATEGORIES = ["CANCELLATION", "FORCE_MAJEURE"]
COUNTER_RESOLUTIONS = ["OPEN", "ACCEPTED", "DECLINED_BY_VENUE"]
COMPLIANCE_STATUSES = [
    "NOT_EVALUATED",
    "COMPLIANT",
    "COMPLIANT_WITH_VARIANCE",
    "NON_COMPLIANT",
]
REVIEW_SOURCES = ["EVENT", "EXTERNAL"]

# --- Logical clock -------------------------------------------------------
# "On startup that instant is exactly 2026-08-01T00:00:00Z".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
# The instant the sourcing scenarios in this suite operate from.
CLOCK_SOURCING_WINDOW = "2026-08-05T09:00:00.000Z"

# --- Total cost model ----------------------------------------------------
CONCESSION_CAP_PCT = 0.08
AV_TIER_1_MAX = 10000.00
AV_TIER_2_MAX = 25000.00
AV_TIER_1_MULTIPLIER = 1.00
AV_TIER_2_MULTIPLIER = 0.95
AV_TIER_3_MULTIPLIER = 0.90
ATTRITION_SHRINK_ASSUMPTION = 0.12
ATTRITION_DAMAGE_PCT = 0.80

# --- Rate benchmark compliance ------------------------------------------
MAX_PROGRAM_PREMIUM_PCT = 0.1000

# --- Volume rebate -------------------------------------------------------
REBATE_TIER_1_MIN = 150000.00
REBATE_TIER_2_MIN = 400000.00
REBATE_PCT_TIER_0 = 0.000
REBATE_PCT_TIER_1 = 0.020
REBATE_PCT_TIER_2 = 0.035

# --- Deposit schedule ----------------------------------------------------
DEPOSIT_PCT = 0.30
DEPOSIT_WEIGHTS = [0.34, 0.33, 0.33]
DEPOSIT_OFFSET_DAYS = [180, 90, 30]

# --- Approval routing ----------------------------------------------------
VP_THRESHOLD_USD = 250000.00
LEGAL_THRESHOLD_USD = 500000.00

# --- Venue performance score --------------------------------------------
PERFORMANCE_WEIGHT_SERVICE = 0.35
PERFORMANCE_WEIGHT_VALUE = 0.25
PERFORMANCE_WEIGHT_AV = 0.20
PERFORMANCE_WEIGHT_RESPONSIVENESS = 0.20
RECENCY_DECAY = 0.7

# --- Termination ---------------------------------------------------------
SECONDS_PER_DAY = 86400

# --- Site inspection -----------------------------------------------------
DEFAULT_TRAVEL_BUFFER_MINUTES = 90
MAX_TRAVEL_BUFFER_MINUTES = 720

# --- Pagination ----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Money -----------------------------------------------------------
MONEY_TOLERANCE = 0.01
PCT_4DP_TOLERANCE = 0.00005
