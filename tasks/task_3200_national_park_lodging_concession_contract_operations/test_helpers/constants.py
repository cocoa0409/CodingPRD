"""Domain constants, enum vocabularies and pinned numeric literals.

Every value here is transcribed from the PRD: the role names of section 2.1,
the enum vocabularies of section 3, and the pinned formula constants
(rate-cap multiplier, deposit rate and cap, refund horizon, no-show grace,
corrective-plan days, cost-overrun cap) of sections 3.2, 3.3, 3.6, 3.8.
"""

# --- Mount points ---------------------------------------------------------

CLOCK_PATH = "/_clock/set_current_utc"

# "Before any clock-setting call, the logical clock reads exactly
# 2026-09-01T00:00:00Z" (PRD 2.4).
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# --- Roles (spelled exactly as in PRD 2.1) --------------------------------

ROLE_CONTRACTING_OFFICER = "AgencyContractingOfficer"
ROLE_RATE_ANALYST = "AgencyRateAnalyst"
ROLE_RATE_MANAGER = "ConcessionerRateManager"
ROLE_OPS_MANAGER = "ConcessionerOpsManager"
ROLE_FRONT_DESK = "ConcessionerFrontDesk"
ROLE_ACCOUNTANT = "ConcessionerAccountant"
ROLE_FINANCIAL_AUDITOR = "AgencyFinancialAuditor"
ROLE_MAINTENANCE_CHIEF = "ConcessionerMaintenanceChief"
ROLE_HR_MANAGER = "ConcessionerHRManager"
ROLE_ENVIRONMENTAL_INSPECTOR = "AgencyEnvironmentalInspector"
ROLE_TEST_HARNESS = "SystemTestHarness"

ALL_ROLES = (
    ROLE_CONTRACTING_OFFICER,
    ROLE_RATE_ANALYST,
    ROLE_RATE_MANAGER,
    ROLE_OPS_MANAGER,
    ROLE_FRONT_DESK,
    ROLE_ACCOUNTANT,
    ROLE_FINANCIAL_AUDITOR,
    ROLE_MAINTENANCE_CHIEF,
    ROLE_HR_MANAGER,
    ROLE_ENVIRONMENTAL_INSPECTOR,
    ROLE_TEST_HARNESS,
)

# --- Contract vocabulary ---------------------------------------------------

CONTRACT_DRAFT = "DRAFT"
CONTRACT_ACTIVE = "ACTIVE"
CONTRACT_EXPIRED = "EXPIRED"
CONTRACT_TRANSITION_PENDING = "TRANSITION_PENDING"
CONTRACT_CLOSED = "CLOSED"

LSI_LINEAR = "LINEAR"
LSI_DECLINING_BALANCE = "DECLINING_BALANCE"

# --- Season vocabulary -----------------------------------------------------

SEASON_PLANNED = "PLANNED"
SEASON_OPEN = "OPEN"
SEASON_CLOSED = "CLOSED"
SEASON_RECONCILED = "RECONCILED"

# --- Service line vocabulary ----------------------------------------------

LINE_LODGING = "LODGING"
LINE_FOOD = "FOOD"
LINE_RETAIL = "RETAIL"
LINE_TOURS = "TOURS"
ALL_LINE_TYPES = (LINE_LODGING, LINE_FOOD, LINE_RETAIL, LINE_TOURS)

LINE_AUTHORIZED = "AUTHORIZED"
LINE_SUSPENDED = "SUSPENDED"
LINE_TERMINATED = "TERMINATED"

# --- Room class vocabulary -------------------------------------------------

ROOM_CLASS_ACTIVE = "ACTIVE"
ROOM_CLASS_DECOMMISSIONED = "DECOMMISSIONED"

# --- Rate filing vocabulary ------------------------------------------------

FILING_SUBMITTED = "SUBMITTED"
FILING_UNDER_REVIEW = "UNDER_REVIEW"
FILING_APPROVED = "APPROVED"
FILING_REJECTED = "REJECTED"
FILING_SUPERSEDED = "SUPERSEDED"
FILING_EXPIRED = "EXPIRED"

BAND_SOLO = "SOLO"
BAND_DOUBLE = "DOUBLE"
BAND_FAMILY = "FAMILY"
ALL_BANDS = (BAND_SOLO, BAND_DOUBLE, BAND_FAMILY)

# --- Comparability study vocabulary ----------------------------------------

STUDY_REGISTERED = "REGISTERED"
STUDY_STALE = "STALE"
STUDY_ARCHIVED = "ARCHIVED"

# --- Reservation vocabulary ------------------------------------------------

RESERVATION_REQUESTED = "REQUESTED"
RESERVATION_CONFIRMED = "CONFIRMED"
RESERVATION_CANCELLED = "CANCELLED"
RESERVATION_NO_SHOW = "NO_SHOW"
RESERVATION_FULFILLED = "FULFILLED"

MODE_BANDED = "BANDED"
MODE_ACTUAL_HEADCOUNT = "ACTUAL_HEADCOUNT"

# --- Receipts report / fee statement vocabulary ----------------------------

REPORT_DRAFT = "DRAFT"
REPORT_SUBMITTED = "SUBMITTED"
REPORT_ACCEPTED = "ACCEPTED"
REPORT_RETURNED = "RETURNED"

STATEMENT_ISSUED = "ISSUED"
STATEMENT_PAID = "PAID"
REPORTING_METHOD_PER_LINE_ROUNDED = "PER_LINE_ROUNDED"

# --- Capital project vocabulary --------------------------------------------

PROJECT_PROPOSED = "PROPOSED"
PROJECT_AUTHORIZED = "AUTHORIZED"
PROJECT_COMPLETED = "COMPLETED"
PROJECT_APPROVED = "APPROVED"
PROJECT_EXPENDED = "EXPENDED"

# --- Housing / hire / voucher vocabulary -----------------------------------

UNIT_AVAILABLE = "AVAILABLE"
UNIT_OFFLINE = "OFFLINE"

HIRE_HIRED = "HIRED"
HIRE_ARRIVED = "ARRIVED"
HIRE_DEPARTED = "DEPARTED"
HIRE_NO_SHOW = "NO_SHOW"
HIRE_TERMINATED = "TERMINATED"

VOUCHER_BOOKED = "BOOKED"
VOUCHER_USED = "USED"
VOUCHER_VOID = "VOID"

# --- Environmental incident vocabulary -------------------------------------

PROTOCOL_WASTE = "WASTE"
PROTOCOL_WATER = "WATER"
PROTOCOL_WILDLIFE = "WILDLIFE"

SEVERITY_MINOR = "MINOR"
SEVERITY_MAJOR = "MAJOR"
SEVERITY_CRITICAL = "CRITICAL"

INCIDENT_REPORTED = "REPORTED"
INCIDENT_UNDER_REVIEW = "UNDER_REVIEW"
INCIDENT_CORRECTIVE_PLAN_REQUIRED = "CORRECTIVE_PLAN_REQUIRED"
INCIDENT_CLOSED = "CLOSED"

# --- Pinned numeric constants (PRD 3.2 / 3.3 / 3.6 / 3.8) -----------------

RATE_CAP_MULTIPLIER = 1.05
DEPOSIT_RATE = 0.2
DEPOSIT_CAP_CENTS = 50000
CANCEL_FULL_REFUND_DAYS = 30
NO_SHOW_GRACE_HOURS = 24
CORRECTIVE_PLAN_DAYS = 14
COST_OVERRUN_CAP_RATE = 1.10

# --- Pagination bounds (PRD 2.3) -------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_MIN = 0

# --- Canonical study fixtures ---------------------------------------------

# A three-comparable study whose weighted mean is exactly 25000 cents:
# (25000*1 + 24000*1 + 26000*1) / 3 = 25000.  Its cap is round(25000*1.05)
# = 26250, so a 26000-cent band passes and 26251 fails.
STUDY_MEAN_25000_COMPARABLES = (
    {"property_name": "A", "nightly_rate_cents": 25000, "weight": 1.0},
    {"property_name": "B", "nightly_rate_cents": 24000, "weight": 1.0},
    {"property_name": "C", "nightly_rate_cents": 26000, "weight": 1.0},
)

# A study whose weighted mean is exactly 20500 cents:
# (20000*1 + 22000*2 + 18000*1) / 4 = 82000 / 4 = 20500.
# Its cap is round(20500*1.05) = 21525 exactly.
STUDY_MEAN_20500_COMPARABLES = (
    {"property_name": "A", "nightly_rate_cents": 20000, "weight": 1.0},
    {"property_name": "B", "nightly_rate_cents": 22000, "weight": 2.0},
    {"property_name": "C", "nightly_rate_cents": 18000, "weight": 1.0},
)

# Standard approved band rates against the 25000-mean study (cap 26250).
RATES_SOLO_19000 = 19000
RATES_DOUBLE_23000 = 23000
RATES_FAMILY_26000 = 26000

# Canonical season geometry: open 2027-06-01, close 2027-09-01,
# lottery opens 2026-12-01.
SEASON_OPEN_2027 = "2027-06-01T00:00:00Z"
SEASON_CLOSE_2027 = "2027-09-01T00:00:00Z"
LOTTERY_OPEN_2027 = "2026-12-01T00:00:00Z"
