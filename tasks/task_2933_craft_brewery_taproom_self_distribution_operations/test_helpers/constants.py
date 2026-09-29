"""Domain constants for the Craft Brewery Taproom & Self-Distribution API.

Every value here is transcribed from the PRD. Nothing is invented: unit
conversions come from §2.6, enumerations from §3.1-§3.9, rates and thresholds
from §3.7 and §3.8.
"""

# ---------------------------------------------------------------------------
# Roles (§2.1)
# ---------------------------------------------------------------------------
ROLE_BREWERY_ADMIN = "BreweryAdmin"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_CELLAR_OPERATOR = "CellarOperator"
ROLE_TAPROOM_STAFF = "TaproomStaff"
ROLE_STATE_REGULATOR = "StateRegulator"

ALL_ROLES = [
    ROLE_BREWERY_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CELLAR_OPERATOR,
    ROLE_TAPROOM_STAFF,
    ROLE_STATE_REGULATOR,
]

# ---------------------------------------------------------------------------
# Logical clock (§2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Unit conversions (§2.6)
# ---------------------------------------------------------------------------
OZ_PER_BBL = 3968
OZ_PER_GAL = 128

BBL_DECIMALS_LEDGER = 3
BBL_DECIMALS_INTENT = 2
OZ_DECIMALS = 2

# ---------------------------------------------------------------------------
# Brewery notice (§3.1)
# ---------------------------------------------------------------------------
NOTICE_PENDING = "PENDING_NOTICE"
NOTICE_ACTIVE = "ACTIVE"
NOTICE_SUSPENDED = "SUSPENDED"
NOTICE_REVOKED = "REVOKED"

NOTICE_ACTION_ACTIVATE = "ACTIVATE"
NOTICE_ACTION_SUSPEND = "SUSPEND"
NOTICE_ACTION_REINSTATE = "REINSTATE"
NOTICE_ACTION_REVOKE = "REVOKE"

# ---------------------------------------------------------------------------
# Beer approval dimensions (§3.1)
# ---------------------------------------------------------------------------
REG_DRAFT = "DRAFT"
REG_FORMULA_PENDING = "FORMULA_PENDING"
REG_FORMULA_APPROVED = "FORMULA_APPROVED"
REG_FORMULA_EXEMPT = "FORMULA_EXEMPT"

LABEL_NO_LABEL = "NO_LABEL"
LABEL_COLA_PENDING = "COLA_PENDING"
LABEL_COLA_APPROVED = "COLA_APPROVED"
LABEL_COLA_REVOKED = "COLA_REVOKED"

FILING_FORMULA = "FORMULA"
FILING_LABEL = "LABEL"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"
DECISION_REVOKED = "REVOKED"

# Beer-level label content (§3.1): four members, no fill_date.
BEER_LABEL_FIELDS = {
    "brand_name": "Cascade Fog",
    "abv_statement": "5.4% ALC/VOL",
    "net_contents": "12 FL OZ",
    "health_warning": "GOVERNMENT WARNING: per 27 CFR 16.21",
}

# Growler/crowler label content (§3.5): the same four plus fill_date.
GROWLER_LABEL_FIELDS = {
    "brand_name": "Cascade Fog",
    "abv_statement": "5.4% ALC/VOL",
    "net_contents": "64 FL OZ",
    "health_warning": "GOVERNMENT WARNING: per 27 CFR 16.21",
    "fill_date": "2026-08-01",
}

CROWLER_LABEL_FIELDS = {
    "brand_name": "Cascade Fog",
    "abv_statement": "5.4% ALC/VOL",
    "net_contents": "32 FL OZ",
    "health_warning": "GOVERNMENT WARNING: per 27 CFR 16.21",
    "fill_date": "2026-08-01",
}

# ---------------------------------------------------------------------------
# Tanks (§3.2)
# ---------------------------------------------------------------------------
TANK_TYPE_FERMENTER = "FERMENTER"
TANK_TYPE_BRITE = "BRITE"

TANK_IDLE = "IDLE"
TANK_OCCUPIED = "OCCUPIED"
TANK_DIRTY = "DIRTY"
TANK_OUT_OF_SERVICE = "OUT_OF_SERVICE"

TANK_ACTION_CIP = "CIP"
TANK_ACTION_TAKE_OUT_OF_SERVICE = "TAKE_OUT_OF_SERVICE"
TANK_ACTION_RETURN_TO_SERVICE = "RETURN_TO_SERVICE"

# Sanitation standard, shared by tank CIP, keg wash and growler fill
# (§3.2, §3.4, §3.5).
SANITIZER_PPM_MIN = 150
SANITIZER_PPM_MAX = 400
CONTACT_TIME_SECONDS_MIN = 60

SANITATION_PASS = "PASS"
SANITATION_NOT_REQUIRED = "NOT_REQUIRED"

# Tank occupation turnaround buffer (§3.2).
TANK_CIP_BUFFER_HOURS = 12

# ---------------------------------------------------------------------------
# Batches (§3.2)
# ---------------------------------------------------------------------------
BATCH_SCHEDULED = "SCHEDULED"
BATCH_BREWING = "BREWING"
BATCH_CONDITIONING = "CONDITIONING"
BATCH_PACKAGED = "PACKAGED"
BATCH_DUMPED = "DUMPED"

LOSS_BASIS_PRO_RATA = "PRO_RATA"
LOSS_BASIS_LAST_RUN_ABSORBS = "LAST_RUN_ABSORBS"

# ---------------------------------------------------------------------------
# Packaging runs (§3.3)
# ---------------------------------------------------------------------------
PACKAGE_HALF_BBL_KEG = "HALF_BBL_KEG"
PACKAGE_QUARTER_BBL_KEG = "QUARTER_BBL_KEG"
PACKAGE_CAN_CASE_24 = "CAN_CASE_24"

BBL_PER_UNIT = {
    PACKAGE_HALF_BBL_KEG: 0.500,
    PACKAGE_QUARTER_BBL_KEG: 0.250,
    PACKAGE_CAN_CASE_24: 0.073,
}

DESTINATION_TAPROOM = "TAPROOM"
DESTINATION_DISTRIBUTION = "DISTRIBUTION"

RUN_PLANNED = "PLANNED"
RUN_COMPLETED = "COMPLETED"
RUN_VOIDED = "VOIDED"

RECON_NOT_APPLICABLE = "NOT_APPLICABLE"
RECON_OPEN = "OPEN"
RECON_RECONCILED = "RECONCILED"

# The batch auto-closes when the resulting remaining_bbl is at most this
# figure, the comparison inclusive (§3.3).
BATCH_AUTO_CLOSE_REMAINING_BBL = 1.000

# ---------------------------------------------------------------------------
# Keg assets (§3.4)
# ---------------------------------------------------------------------------
KEG_EMPTY_DIRTY = "EMPTY_DIRTY"
KEG_CLEANED = "CLEANED"
KEG_FILLED = "FILLED"
KEG_TAPPED = "TAPPED"
KEG_DEPLOYED = "DEPLOYED"
KEG_DECOMMISSIONED = "DECOMMISSIONED"

KEG_SIZE_HALF_BBL = 0.5
KEG_SIZE_QUARTER_BBL = 0.25

MOVEMENT_TAP = "TAP"
MOVEMENT_DEPLOY_DISTRIBUTION = "DEPLOY_DISTRIBUTION"
MOVEMENT_DEPLOY_EVENT = "DEPLOY_EVENT"
MOVEMENT_RETURN = "RETURN"
MOVEMENT_DECOMMISSION = "DECOMMISSION"

CHANNEL_TAPROOM = "TAPROOM"
CHANNEL_DISTRIBUTION = "DISTRIBUTION"
CHANNEL_EVENT = "EVENT"

# Shrinkage tolerance is two percent of filled_volume_oz (§3.4).
KEG_SHRINKAGE_TOLERANCE_PCT = 0.02

# ---------------------------------------------------------------------------
# Taproom pours (§3.5)
# ---------------------------------------------------------------------------
CONTAINER_SAMPLE_4OZ = "SAMPLE_4OZ"
CONTAINER_HALF_PINT_8OZ = "HALF_PINT_8OZ"
CONTAINER_PINT_16OZ = "PINT_16OZ"
CONTAINER_CROWLER_32OZ = "CROWLER_32OZ"
CONTAINER_GROWLER_64OZ = "GROWLER_64OZ"

POUR_OZ = {
    CONTAINER_SAMPLE_4OZ: 4,
    CONTAINER_HALF_PINT_8OZ: 8,
    CONTAINER_PINT_16OZ: 16,
    CONTAINER_CROWLER_32OZ: 32,
    CONTAINER_GROWLER_64OZ: 64,
}

SEALED_CONTAINER_TYPES = [CONTAINER_CROWLER_32OZ, CONTAINER_GROWLER_64OZ]
DRAFT_CONTAINER_TYPES = [
    CONTAINER_SAMPLE_4OZ,
    CONTAINER_HALF_PINT_8OZ,
    CONTAINER_PINT_16OZ,
]

# ---------------------------------------------------------------------------
# State licences and appointments (§3.6)
# ---------------------------------------------------------------------------
LICENSE_SELF_DISTRIBUTION = "SELF_DISTRIBUTION"
LICENSE_WHOLESALER_ONLY = "WHOLESALER_ONLY"

LICENSE_ACTIVE = "ACTIVE"
LICENSE_SUSPENDED = "SUSPENDED"
LICENSE_EXPIRED = "EXPIRED"

DEFAULT_TERMINATION_NOTICE_DAYS = 90

APPT_PROPOSED = "PROPOSED"
APPT_ACTIVE = "ACTIVE"
APPT_TERMINATION_REQUESTED = "TERMINATION_REQUESTED"
APPT_TERMINATED = "TERMINATED"

SCOPE_ALL_BRANDS = "ALL_BRANDS"
SCOPE_SINGLE_BRAND = "SINGLE_BRAND"

TERMINATION_REQUEST = "REQUEST"
TERMINATION_WITHDRAW = "WITHDRAW"
TERMINATION_FINALIZE = "FINALIZE"

GOOD_CAUSE_NONPAYMENT = "NONPAYMENT"
GOOD_CAUSE_BREACH_OF_CONTRACT = "BREACH_OF_CONTRACT"
GOOD_CAUSE_LOSS_OF_LICENSE = "LOSS_OF_LICENSE"
GOOD_CAUSE_VOLUNTARY_MUTUAL = "VOLUNTARY_MUTUAL"

# ---------------------------------------------------------------------------
# Distribution orders (§3.7)
# ---------------------------------------------------------------------------
ORDER_SUBMITTED = "SUBMITTED"
ORDER_ALLOCATED = "ALLOCATED"
ORDER_SHIPPED = "SHIPPED"
ORDER_REJECTED = "REJECTED"
ORDER_CANCELLED = "CANCELLED"

ORDER_CHANNEL_SELF_DISTRIBUTED = "SELF_DISTRIBUTED"
ORDER_CHANNEL_WHOLESALER = "WHOLESALER"

REJECTION_NOTICE_SUSPENDED = "NOTICE_SUSPENDED"
REJECTION_LICENSE_NOT_ACTIVE = "LICENSE_NOT_ACTIVE"
REJECTION_LABEL_REVOKED = "LABEL_REVOKED"
REJECTION_APPOINTMENT_ACTIVATED = "APPOINTMENT_ACTIVATED"
REJECTION_INSUFFICIENT_INVENTORY = "INSUFFICIENT_INVENTORY"

# Landed-cost arithmetic (§3.7).
FREIGHT_CENTS_PER_MILE = 30
FREIGHT_CENTS_PER_BBL = 1200
FREIGHT_DISCOUNT_TIERS = [
    (400000, 0.30),
    (200000, 0.20),
    (100000, 0.10),
]
FRANCHISE_FEE_PCT = 0.03

# ---------------------------------------------------------------------------
# Excise reports (§3.8)
# ---------------------------------------------------------------------------
BASIS_METERED_POUR = "METERED_POUR"
BASIS_WHOLE_KEG_REMOVAL = "WHOLE_KEG_REMOVAL"

REPORT_DRAFT = "DRAFT"
REPORT_FILED = "FILED"
REPORT_SUPERSEDED = "SUPERSEDED"

FEDERAL_REDUCED_TIER_LIMIT_BBL = 60000
FEDERAL_REDUCED_CENTS_PER_BBL = 350
FEDERAL_STANDARD_CENTS_PER_BBL = 1600

STATE_TAPROOM_CENTS_PER_BBL = 1085
STATE_DISTRIBUTION_CENTS_PER_BBL = 870
STATE_SMALL_BREWER_CREDIT_LIMIT_BBL = 15000
STATE_SMALL_BREWER_CREDIT_PCT = 0.50

# ---------------------------------------------------------------------------
# Event permits (§3.9)
# ---------------------------------------------------------------------------
PERMIT_FESTIVAL = "FESTIVAL"
PERMIT_OFF_SITE_TASTING = "OFF_SITE_TASTING"
PERMIT_FARMERS_MARKET = "FARMERS_MARKET"

PERMIT_DRAFT = "DRAFT"
PERMIT_SUBMITTED = "SUBMITTED"
PERMIT_INFO_REQUESTED = "INFO_REQUESTED"
PERMIT_APPROVED = "APPROVED"
PERMIT_DENIED = "DENIED"

PERMIT_DECISION_APPROVED = "APPROVED"
PERMIT_DECISION_DENIED = "DENIED"
PERMIT_DECISION_INFO_REQUESTED = "INFO_REQUESTED"

EVENT_ANNUAL_BBL_CAP_PER_STATE = 25.00
EVENT_MAX_CONCURRENT_APPROVED_PER_STATE = 2

# ---------------------------------------------------------------------------
# A well-formed UUID that never names a row (§2.4 identifiers are UUIDs)
# ---------------------------------------------------------------------------
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# ---------------------------------------------------------------------------
# Pagination (§2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
