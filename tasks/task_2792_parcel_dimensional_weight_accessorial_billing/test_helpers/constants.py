"""Business constants for the parcel dimensional-weight and accessorial billing API.

Every value here is fixed by the PRD. Tests import these names instead of
repeating magic numbers, so a single edit tracks a contract change.

All monetary amounts are integer minor units (US cents). They are sent to the
API as JSON numbers, never as strings.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_CARRIER_ADMIN = "CarrierAdmin"
ROLE_CARRIER_OPS = "CarrierOps"
ROLE_BILLING_OPS = "BillingOps"
ROLE_REVENUE_AUDITOR = "RevenueAuditor"
ROLE_SHIPPER_USER = "ShipperUser"

ALL_ROLES = [
    ROLE_CARRIER_ADMIN,
    ROLE_CARRIER_OPS,
    ROLE_BILLING_OPS,
    ROLE_REVENUE_AUDITOR,
    ROLE_SHIPPER_USER,
]

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Oversize / additional-handling thresholds
# ---------------------------------------------------------------------------
OVERSIZE_MIN_BILLABLE_LBS = 90
OVERSIZE_LONGEST_IN = 96
OVERSIZE_LENGTH_PLUS_GIRTH_IN = 130
AH_WEIGHT_LBS = 50
AH_LONGEST_IN = 48

# ---------------------------------------------------------------------------
# Carrier default accessorial rates (cents)
# ---------------------------------------------------------------------------
DEFAULT_RATE_CENTS = {
    "RESIDENTIAL": 590,
    "OVERSIZE": 12500,
    "ADDITIONAL_HANDLING": 2450,
    "ADDRESS_CORRECTION": 2200,
    "RETURN_UNDELIVERABLE": 1800,
    "REFUSAL": 1350,
}

# Delivery-area rates are keyed by the shipment's delivery_area_class.
DAS_RATE_CENTS = {
    "NONE": 0,
    "DAS": 425,
    "EXTENDED": 650,
}

# ---------------------------------------------------------------------------
# Scan tolerance constants
# ---------------------------------------------------------------------------
DIM_VARIANCE_TOLERANCE_PCT = 5.00
WEIGHT_VARIANCE_ABS_LBS = 0.5
WEIGHT_VARIANCE_PCT = 2.00

# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
CLAIM_WINDOW_DAYS = 15
DISPUTE_WINDOW_DAYS = 90
MAX_EVIDENCE_ROUNDS = 2

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SHIPPER_STATUSES = ["ACTIVE", "SUSPENDED"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED"]
WINDOW_STATUSES = ["SCHEDULED", "ACTIVE", "CANCELLED"]
WINDOW_KINDS = ["PEAK_SEASON", "DEMAND"]
MEASUREMENT_STATUSES = ["PENDING_SCAN", "SCANNED", "TOLERANCE_FLAGGED", "VERIFIED"]
MOVEMENT_STATUSES = [
    "IN_TRANSIT",
    "DELIVERED",
    "UNDELIVERABLE",
    "REFUSED",
]
BILLING_STATUSES = ["UNBILLED", "BILLED", "ADJUSTED"]
INVOICE_STATUSES = ["OPEN", "ISSUED", "ADJUSTED", "SETTLED", "VOID"]
ADJUSTMENT_STATUSES = ["PROPOSED", "APPLIED", "REJECTED"]
ADJUSTMENT_REASONS = [
    "WEIGHT_CORRECTION",
    "ACCESSORIAL_CORRECTION",
    "DISPUTE_CREDIT",
    "GUARANTEE_REFUND",
    "MANUAL",
]
DISPUTE_STATUSES = [
    "SUBMITTED",
    "EVIDENCE_REQUESTED",
    "UNDER_REVIEW",
    "UPHELD",
    "DENIED",
]
DISPUTE_CLAIM_TYPES = ["WEIGHT", "ACCESSORIAL"]
CLAIM_STATUSES = ["FILED", "APPROVED", "DENIED", "REFUNDED"]
SCAN_SOURCES = ["AUTOMATED_DWS", "MANUAL_REWEIGH"]
TOLERANCE_STATUSES = ["WITHIN_TOLERANCE", "EXCEEDS_TOLERANCE"]
BASIS_VALUES = ["ACTUAL", "DIMENSIONAL", "OVERSIZE_FLOOR"]
ACCESSORIAL_CODES = [
    "RESIDENTIAL",
    "DELIVERY_AREA",
    "OVERSIZE",
    "ADDITIONAL_HANDLING",
    "ADDRESS_CORRECTION",
    "RETURN_UNDELIVERABLE",
    "REFUSAL",
]
EXCEPTION_KINDS = ["UNDELIVERABLE", "REFUSED", "ADDRESS_CORRECTED"]
EVIDENCE_ITEM_TYPES = ["SCAN_IMAGE", "DELIVERY_PHOTO", "ADDRESS_PROOF", "SCALE_CERT"]

# The literal actor recorded on engine-minted billing adjustments.
SYSTEM_ACTOR = "system"

# ---------------------------------------------------------------------------
# The reference rate contract shape used across the suite
# ---------------------------------------------------------------------------
STD_DIM_DIVISOR = 139
STD_MIN_CHARGE_CENTS = 1195

ZONE2_RATE_ROWS = [
    {"zone": 2, "min_lbs": 1, "max_lbs": 20, "cents_per_lb": 380},
    {"zone": 2, "min_lbs": 21, "max_lbs": 70, "cents_per_lb": 340},
    {"zone": 2, "min_lbs": 71, "max_lbs": 9999, "cents_per_lb": 305},
]

ZONE5_RATE_ROWS = [
    {"zone": 5, "min_lbs": 1, "max_lbs": 20, "cents_per_lb": 520},
    {"zone": 5, "min_lbs": 21, "max_lbs": 70, "cents_per_lb": 470},
    {"zone": 5, "min_lbs": 71, "max_lbs": 9999, "cents_per_lb": 425},
]

TIER_ROW_550 = {"min_transportation_subtotal_cents": 50000, "discount_bps": 550}
TIER_ROW_1250 = {"min_transportation_subtotal_cents": 250000, "discount_bps": 1250}

STD_TIER_TABLE = [TIER_ROW_550]
FULL_TIER_TABLE = [TIER_ROW_550, TIER_ROW_1250]

RESIDENTIAL_OVERRIDE_540 = {"RESIDENTIAL": 540}
