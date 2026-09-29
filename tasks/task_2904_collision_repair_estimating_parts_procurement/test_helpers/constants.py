"""Domain constants for the collision repair estimating and parts procurement API.

Every value here is transcribed from the product requirements document. Nothing
is inferred: rate cards, thresholds, tier floors, default field values and enum
memberships are all stated explicitly by the contract under test.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_SHOP_ADMIN = "ShopAdmin"
ROLE_ESTIMATOR = "Estimator"
ROLE_PARTS_MANAGER = "PartsManager"
ROLE_TECHNICIAN = "Technician"
ROLE_QC_INSPECTOR = "QcInspector"
ROLE_INSURER_ADJUSTER = "InsurerAdjuster"
ROLE_CUSTOMER = "Customer"

ALL_ROLES = (
    ROLE_SHOP_ADMIN,
    ROLE_ESTIMATOR,
    ROLE_PARTS_MANAGER,
    ROLE_TECHNICIAN,
    ROLE_QC_INSPECTOR,
    ROLE_INSURER_ADJUSTER,
    ROLE_CUSTOMER,
)

UNDECLARED_ROLE = "Painter"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_MIN = 0

# ---------------------------------------------------------------------------
# Labor rate card (shop posted rates, cents per hour) -- a system constant
# ---------------------------------------------------------------------------
POSTED_RATE_CENTS = {
    "BODY": 6500,
    "FRAME": 8500,
    "REFINISH": 6000,
    "MECHANICAL": 12500,
    "ALUMINUM_BODY": 9500,
}

# The insurer program carries `rate_ceiling_cents`, an object keyed by labor
# type, and every one of the five keys is required.
LABOR_TYPES = ("BODY", "FRAME", "REFINISH", "MECHANICAL", "ALUMINUM_BODY")

# A ceiling block that sits below every posted rate, so the rate applied to a
# line is the ceiling for all five labor types. These are the figures the
# product requirements use in their own worked pass through the totals.
CEILINGS_BELOW_POSTED = {
    "BODY": 6000,
    "FRAME": 8000,
    "REFINISH": 5800,
    "MECHANICAL": 11000,
    "ALUMINUM_BODY": 8800,
}

# A ceiling block that sits above every posted rate, so the applied rate is the
# posted rate for all five labor types.
CEILINGS_ABOVE_POSTED = {
    "BODY": 9900,
    "FRAME": 9900,
    "REFINISH": 9900,
    "MECHANICAL": 13500,
    "ALUMINUM_BODY": 9900,
}

# ---------------------------------------------------------------------------
# Refinish allocation
# ---------------------------------------------------------------------------
TWO_STAGE_ADDER_HOURS = 0.3
BLEND_FACTOR = 0.5
ADJACENT_DEDUCTION_HOURS = 0.4

# ---------------------------------------------------------------------------
# The eight-step totals
# ---------------------------------------------------------------------------
SUPPLIES_FEE_PCT = 0.04
SUPPLIES_FEE_CAP_CENTS = 25000
BETTERMENT_SHARE = 0.2
DEFAULT_DEDUCTIBLE_CENTS = 50000

REBATE_TIER_MID_FLOOR_CENTS = 100000
REBATE_TIER_TOP_FLOOR_CENTS = 500000
REBATE_RATE_LOW = 0.0
REBATE_RATE_MID = 0.03
REBATE_RATE_TOP = 0.05

# ---------------------------------------------------------------------------
# Customer consent
# ---------------------------------------------------------------------------
CONSENT_THRESHOLD_CENTS = 50000

# ---------------------------------------------------------------------------
# Supplier performance scoring
# ---------------------------------------------------------------------------
VENDOR_SCORE_DEFAULT = 50
VENDOR_SCORE_FLOOR = 40
VENDOR_SCORE_SCALE = 100
WEIGHT_ON_TIME = 0.6
WEIGHT_NO_RETURN = 0.25
WEIGHT_FIRST_ROUND = 0.15
ROLLING_WINDOW_SIZE = 3

# ---------------------------------------------------------------------------
# Declared defaults -- suppliers
# ---------------------------------------------------------------------------
DEFAULT_VENDOR_STATUS = "ACTIVE"
DEFAULT_DISCOUNT_PCT = 0
DEFAULT_CORE_CHARGE_CENTS = 0
DEFAULT_RESTOCKING_FEE_PCT = 0.2
DEFAULT_MAX_QTY_PER_LINE = 4
DEFAULT_ORDER_SEQ_COUNTER = 0

# ---------------------------------------------------------------------------
# Declared defaults -- insurer programs
# ---------------------------------------------------------------------------
DEFAULT_AFTERMARKET_ALLOWED = True
DEFAULT_RECYCLED_ALLOWED = True
DEFAULT_RECONDITIONED_ALLOWED = False
DEFAULT_ALTERNATE_PARTS_MIN_VEHICLE_AGE_YEARS = 3
DEFAULT_PARTS_PRICE_CEILING_PCT = 1.1
DEFAULT_SUPPLEMENT_ROUND_LIMIT = 3

# ---------------------------------------------------------------------------
# Declared defaults -- shop capacity
# ---------------------------------------------------------------------------
DEFAULT_CLEANUP_BUFFER_MINUTES = 30
DEFAULT_STALL_STATUS = "AVAILABLE"
DEFAULT_CONCURRENT_CAPACITY = 2

# ---------------------------------------------------------------------------
# Warranty certificate
# ---------------------------------------------------------------------------
WARRANTY_PREFIX = "WC-"
WARRANTY_TERM_DAYS = 365

# ---------------------------------------------------------------------------
# Vehicle bounds
# ---------------------------------------------------------------------------
MODEL_YEAR_MIN = 1980
MODEL_YEAR_MAX = 2100
VIN_LENGTH = 17

# ---------------------------------------------------------------------------
# Repair order stages
# ---------------------------------------------------------------------------
STAGE_INTAKE = "INTAKE"
STAGE_TEARDOWN = "TEARDOWN"
STAGE_BLUEPRINTED = "BLUEPRINTED"
STAGE_ESTIMATE_LOCKED = "ESTIMATE_LOCKED"
STAGE_PARTS_STAGED = "PARTS_STAGED"
STAGE_REPAIR = "REPAIR"
STAGE_REFINISH_CALIBRATION = "REFINISH_CALIBRATION"
STAGE_READY_FOR_QC = "READY_FOR_QC"
STAGE_QC_FAILED = "QC_FAILED"
STAGE_DELIVERED = "DELIVERED"
STAGE_TOTAL_LOSS = "TOTAL_LOSS"

# The forward walk a healthy order takes, one hop at a time.
FORWARD_STAGES = (
    STAGE_PARTS_STAGED,
    STAGE_REPAIR,
    STAGE_REFINISH_CALIBRATION,
    STAGE_READY_FOR_QC,
)

TERMINAL_STAGES = (STAGE_DELIVERED, STAGE_TOTAL_LOSS)

# ---------------------------------------------------------------------------
# Authorisation dimensions
# ---------------------------------------------------------------------------
POSTURE_OPEN = "OPEN"
POSTURE_SUPPLEMENT_PENDING = "SUPPLEMENT_PENDING"
POSTURE_CONSENT_REQUIRED = "CONSENT_REQUIRED"
AUTHORIZATION_POSTURES = (
    POSTURE_OPEN,
    POSTURE_SUPPLEMENT_PENDING,
    POSTURE_CONSENT_REQUIRED,
)

CONSENT_STATES = ("NONE", "CONSENTED", "DECLINED")
CONSENT_DECISIONS = ("CONSENT", "DECLINE")

AUTH_INSURER_ALLOWED = "INSURER_ALLOWED"
AUTH_CUSTOMER_CONSENTED = "CUSTOMER_CONSENTED"
AUTH_PENDING_CONSENT = "PENDING_CONSENT"
AUTH_CUSTOMER_DECLINED = "CUSTOMER_DECLINED"
AUTHORIZATION_STATUSES = (
    AUTH_INSURER_ALLOWED,
    AUTH_CUSTOMER_CONSENTED,
    AUTH_PENDING_CONSENT,
    AUTH_CUSTOMER_DECLINED,
)

# ---------------------------------------------------------------------------
# Teardown findings and labor lines
# ---------------------------------------------------------------------------
SEVERITIES = ("LIGHT", "MODERATE", "SEVERE")

DISCOVERY_STAGES = (
    STAGE_TEARDOWN,
    STAGE_BLUEPRINTED,
    STAGE_ESTIMATE_LOCKED,
    STAGE_PARTS_STAGED,
    STAGE_REPAIR,
    STAGE_REFINISH_CALIBRATION,
    STAGE_READY_FOR_QC,
    STAGE_QC_FAILED,
)

LINE_STATUSES = ("DRAFT", "PENDING_SUPPLEMENT", "APPROVED", "REJECTED", "VOID")
PAY_TYPES = ("INSURER", "CUSTOMER")

# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------
PART_TYPES = ("OEM", "AFTERMARKET", "RECYCLED", "RECONDITIONED")
VENDOR_TYPES = (
    "OEM_DEALER",
    "AFTERMARKET_DISTRIBUTOR",
    "RECYCLER",
    "RECONDITIONER",
)
VENDOR_STATUSES = ("ACTIVE", "SUSPENDED")

PROCUREMENT_STATUSES = (
    "PLANNED",
    "QUOTED",
    "COUNTERED",
    "PRICE_LOCKED",
    "ORDERED",
    "RECEIVED",
    "INSTALLED",
    "RETURNED",
    "VOID",
)

RECEIVE_CONDITIONS = ("CORRECT", "INCORRECT", "DAMAGED")
RETURN_REASONS = ("UNUSED", "INCORRECT", "DAMAGED")
DELAY_REASONS = ("ETA_BREACH", "INCORRECT_PART")

# ---------------------------------------------------------------------------
# Supplements
# ---------------------------------------------------------------------------
SUPPLEMENT_STATUSES = (
    "SUBMITTED",
    "INFO_REQUESTED",
    "APPROVED",
    "PARTIAL",
    "DENIED",
)
SUPPLEMENT_REASON_CODES = (
    "HIDDEN_DAMAGE",
    "PROCEDURE_REQUIREMENT",
    "PARTS_PRICE_VARIANCE",
    "CALIBRATION_REQUIRED",
)
SUPPLEMENT_DECISIONS = ("APPROVE", "PARTIAL", "DENY", "REQUEST_INFO")

# ---------------------------------------------------------------------------
# Procedure research and calibration
# ---------------------------------------------------------------------------
PROCEDURE_SOURCES = ("OEM_PORTAL", "ALLDATA", "IREPAIR")
OPERATION_SCOPES = ("STRUCTURAL", "REFINISH", "ADAS", "MECHANICAL")
CALIBRATION_TYPES = ("NONE", "STATIC", "DYNAMIC", "BOTH")
CALIBRATION_STATUSES = (
    "NOT_REQUIRED",
    "REQUIRED",
    "SCHEDULED",
    "PASSED",
    "FAILED",
)
BAY_SUPPORTED_TYPES = ("STATIC", "DYNAMIC", "BOTH")

# ---------------------------------------------------------------------------
# Shop capacity and bookings
# ---------------------------------------------------------------------------
STALL_TYPES = ("BODY", "FRAME", "PAINT")
STALL_STATUSES = ("AVAILABLE", "MAINTENANCE")
ASSIGNMENT_STAGES = (STAGE_REPAIR, STAGE_REFINISH_CALIBRATION)
ASSIGNMENT_STATUSES = ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")

# ---------------------------------------------------------------------------
# Quality control
# ---------------------------------------------------------------------------
QC_RESULTS = ("PASS", "FAIL")
QC_FAILURE_REASONS = ("CHECKLIST", "DTC_PRESENT")

# ---------------------------------------------------------------------------
# Well-known identifiers
# ---------------------------------------------------------------------------
ABSENT_UUID = "00000000-0000-4000-8000-000000000404"
