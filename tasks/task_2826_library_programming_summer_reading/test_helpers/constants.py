"""Domain constants for the Library Programming & Summer Reading API.

Every value here is taken from the PRD under test: the API mount point, the
enumerations, the logical-clock default and the calculation constants used by
the contract-pricing, supply-draw, prize-award, screening-validity and
kill-fee formulas.
"""

# --------------------------------------------------------------------------
# Mount point
# --------------------------------------------------------------------------
BASE = "/library"
CLOCK_SET_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# Roles (PRD section 2.1: "spelled exactly ProgramManager, ProgramCoordinator,
# ScreeningOfficer and Reader")
# --------------------------------------------------------------------------
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_PROGRAM_COORDINATOR = "ProgramCoordinator"
ROLE_SCREENING_OFFICER = "ScreeningOfficer"
ROLE_READER = "Reader"

ALL_ROLES = (
    ROLE_PROGRAM_MANAGER,
    ROLE_PROGRAM_COORDINATOR,
    ROLE_SCREENING_OFFICER,
    ROLE_READER,
)

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
# "At server startup the logical clock reads exactly 2026-08-01T00:00:00.000Z."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
ROOM_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")
ACCESSIBILITY_FEATURES = (
    "WHEELCHAIR_ACCESSIBLE",
    "HEARING_LOOP",
    "ADJUSTABLE_LIGHTING",
    "QUIET_ZONE",
)
ACCOMMODATIONS = (
    "WHEELCHAIR_LAYOUT",
    "ASL_INTERPRETER",
    "SENSORY_QUIET_HOUR",
    "LARGE_PRINT_HANDOUTS",
)
# "WHEELCHAIR_LAYOUT requires WHEELCHAIR_ACCESSIBLE, ASL_INTERPRETER requires
# HEARING_LOOP, SENSORY_QUIET_HOUR requires QUIET_ZONE and
# LARGE_PRINT_HANDOUTS carries no room requirement."
ACCOMMODATION_TO_FEATURE = {
    "WHEELCHAIR_LAYOUT": "WHEELCHAIR_ACCESSIBLE",
    "ASL_INTERPRETER": "HEARING_LOOP",
    "SENSORY_QUIET_HOUR": "QUIET_ZONE",
    "LARGE_PRINT_HANDOUTS": None,
}

AGE_GROUPS = ("EARLY_CHILDHOOD", "SCHOOL_AGE", "TEEN", "ADULT", "ALL_AGES")
DELIVERY_MODES = ("IN_BRANCH", "PARTNER_SITE")
REGISTRATION_POLICIES = ("REGISTRATION", "DROP_IN")
PARTNER_TYPES = ("NONE", "SCHOOL", "NONPROFIT", "MUSEUM", "BUSINESS")

PROGRAM_OPERATIONAL_STATUSES = (
    "DRAFT",
    "SCHEDULED",
    "CONFIRMED",
    "CLOSED_OUT",
    "WEATHER_CLOSED",
    "CANCELLED",
)
PROGRAM_COMPLIANCE_STATUSES = (
    "UNVERIFIED",
    "PENDING_SCREENING",
    "CLEARED",
    "BLOCKED",
)
BUDGET_POSTURES = ("WITHIN_BUDGET", "OVER_BUDGET")

RESERVATION_STATUSES = ("HELD", "CONFIRMED", "RELEASED", "SUPERSEDED")

PRESENTER_TYPES = ("INDIVIDUAL", "AGENCY")
ENGAGEMENT_STATUSES = ("PROSPECT", "ACTIVE", "SUSPENDED")
SCREENING_TIERS = ("NONE", "NAME_CHECK", "FINGERPRINT")
SCREENING_DECISIONS = (
    "NONE",
    "PENDING",
    "CLEAR",
    "FLAGGED",
    "CLEARED_WITH_CONDITIONS",
    "DENIED",
)
SCREENING_STATUSES = (
    "NONE",
    "PENDING",
    "ACTIVE",
    "EXPIRED",
    "PENDING_ADJUDICATION",
    "BLOCKED",
)

CONTRACT_STATUSES = (
    "DRAFT",
    "OFFERED",
    "COUNTERED",
    "EXECUTED",
    "BLOCKED",
    "COMPLETED",
    "CANCELLED_WEATHER",
    "CANCELLED_LIBRARY",
)

CHALLENGE_STATUSES = ("PLANNING", "OPEN", "RECONCILED")
LOGGING_METHODS = ("MINUTES", "BOOKS", "ACTIVITIES")
CORRECTION_POLICIES = ("HIGH_WATER", "LEDGER_TRUTH")
PRIZE_INVENTORY_POSTURES = ("AMPLE", "CONSTRAINED")

AGE_BANDS = ("UNDER_5", "AGE_5_11", "AGE_12_17", "ADULT")
LOG_SOURCES = ("SELF_SERVICE", "STAFF_DESK", "OUTREACH_SITE")
ENTRY_TYPES = ("LOG", "CORRECTION")

LOT_CATEGORIES = ("PRIZE", "SUPPLY")
LOT_STATUSES = ("ACTIVE", "DEPLETED")

AWARD_STATUSES = ("RESERVED", "DEFERRED", "ISSUED", "FORFEITED", "REVOKED")

# --------------------------------------------------------------------------
# Calculation constants
# --------------------------------------------------------------------------
# Contract travel reimbursement.
MILEAGE_FREE_MILES = 20
MILEAGE_TIER1_LIMIT_MILES = 60
MILEAGE_TIER1_RATE_CENTS = 65
MILEAGE_TIER2_RATE_CENTS = 45

# Contract surcharges and premiums.
MINORS_ESCORT_FEE_CENTS = 4000
INSURANCE_RIDER_FEE_CENTS = 2500
INSURANCE_RIDER_WINDOW_DAYS = 30
WEEKEND_PREMIUM_RATE = 0.10
PROGRAM_FEE_CAP_CENTS = 250000

# Cancellation kill fees.
WEATHER_KILL_FEE_RATE = 0.50
WEATHER_KILL_FEE_WINDOW_HOURS = 48
LIBRARY_CANCEL_LATE_WINDOW_DAYS = 14
LIBRARY_CANCEL_EARLY_RATE = 0.25

# Presenter engagement window padding.
PRESENTER_TRAVEL_BUFFER_MINUTES = 90

# Screening validity.
SCREENING_VALIDITY_DAYS_NAME_CHECK = 365
SCREENING_VALIDITY_DAYS_FINGERPRINT = 730

# Room accessibility.
ACCESSIBLE_SETUP_MINUTES = 30
WHEELCHAIR_LAYOUT_SEAT_LOSS_RATE = 0.15

# Supply and prize sourcing.
CROSS_BRANCH_SURCHARGE_RATE = 0.08
MATERIALS_CONTINGENCY_LOW_RATE = 0.10
MATERIALS_CONTINGENCY_HIGH_RATE = 0.05
MATERIALS_CONTINGENCY_THRESHOLD_CENTS = 20000

# Per-date logging caps, selected by the challenge's logging_method.
DAILY_LOG_CAP_MINUTES = 300
DAILY_LOG_CAP_BOOKS = 10
DAILY_LOG_CAP_ACTIVITIES = 5
DAILY_LOG_CAPS = {
    "MINUTES": DAILY_LOG_CAP_MINUTES,
    "BOOKS": DAILY_LOG_CAP_BOOKS,
    "ACTIVITIES": DAILY_LOG_CAP_ACTIVITIES,
}
