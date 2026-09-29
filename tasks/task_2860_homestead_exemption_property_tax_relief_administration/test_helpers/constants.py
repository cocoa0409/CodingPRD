"""Domain constants pinned by the PRD.

Money is always an integer count of cents and every rate is an integer count of
basis points, where 10000 basis points express one whole unit.  No monetary or
rate value is ever transmitted as a JSON string.
"""

# --- logical clock -------------------------------------------------------

# The clock starts at a fixed instant and only moves when a ProgramAdministrator
# supplies a new instant.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- basis points and pinned rates --------------------------------------

BPS_DENOMINATOR = 10000

# Annual growth cap applied to the base-year value when a parcel omits its own.
DEFAULT_ASSESSMENT_CAP_PCT_BPS = 200

# County-wide mill rate used by the retroactive refund calculation.
COUNTY_MILL_RATE_BPS = 125

# Simple statutory interest on un-offset refund remainders, per elapsed year.
REFUND_INTEREST_BPS_PER_YEAR = 400

# --- fraud risk scoring --------------------------------------------------

RISK_WEIGHT_ADDRESS_MISMATCH = 3500
RISK_WEIGHT_INCOME_MISMATCH = 3000
RISK_WEIGHT_POSTAL_FORWARD = 1500
RISK_WEIGHT_OCCUPANCY_GAP = 2000
RISK_SUBSTANTIATION_THRESHOLD = 60

# --- portability ---------------------------------------------------------

MIN_PORTABLE_ALLOCATION_CENTS = 1

# --- bounded cycles and windows -----------------------------------------

MAX_INFO_REQUEST_ROUNDS = 2
MAX_CONTINUANCES = 2
APPEAL_WINDOW_DAYS = 30
HEARING_BUFFER_MINUTES = 15

# --- pagination ----------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- enumerations --------------------------------------------------------

ROLES = (
    "Taxpayer",
    "ProgramAdministrator",
    "AssessorAnalyst",
    "IntakeClerk",
    "ExemptionsReviewer",
    "FraudInvestigator",
    "RecoveryOfficer",
    "HearingClerk",
    "HearingOfficer",
)

PROGRAM_CODES = (
    "HOMESTEAD_BASIC",
    "SENIOR_FREEZE",
    "VETERAN_DISABILITY",
    "DISABILITY_INCOME",
    "AGRICULTURAL_USE",
)

COUNTY_ZONES = ("NORTH", "SOUTH", "EAST", "WEST")

OCCUPANCY_TYPES = ("PRIMARY_RESIDENCE", "SECONDARY", "RENTAL", "AGRICULTURAL")

OWNERSHIP_SOURCE_SYSTEMS = ("DEED_REGISTRY", "FIELD_INSPECTION", "TAXPAYER_AFFIDAVIT")

VERIFICATION_SOURCES = (
    "VOTER_REGISTRY",
    "DMV",
    "USPS_NCOA",
    "INCOME_DOR",
    "DEED_REGISTRY",
)

VERIFICATION_RESULTS = ("MATCH", "MISMATCH", "NO_RECORD")

PARCEL_EXEMPTION_STATUSES = ("UNEXEMPTED", "PARTIALLY_EXEMPT", "FULLY_EXEMPT")

APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "APPROVED",
    "DENIED",
)

GRANT_STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED", "TRANSFERRED", "LAPSED")

SUSPENSION_REASONS = (
    "FRAUD_INVESTIGATION",
    "RECERTIFICATION_LAPSE",
    "OCCUPANCY_LOST",
)

CERTIFICATION_STATUSES = ("PENDING", "CERTIFIED", "LAPSED", "REVOKED")

RELIEF_TIERS = ("NOT_ASSESSED", "TIER_FULL", "TIER_HIGH", "TIER_PARTIAL")

# Multiplier implied by each income tier, in basis points.
TIER_MULTIPLIER_BPS = {
    "NOT_ASSESSED": 0,
    "TIER_FULL": 10000,
    "TIER_HIGH": 7500,
    "TIER_PARTIAL": 5000,
}

CLAIM_STATUSES = ("PENDING", "APPROVED", "DENIED", "REVERSED")

INVESTIGATION_STATUSES = ("OPEN", "SUBSTANTIATED", "CLEARED")

RECOVERY_STATUSES = ("NONE", "ASSESSED", "PARTIALLY_PAID", "PAID", "ABATED")

ACCOUNT_STATUSES = ("GOOD_STANDING", "FLAGGED", "BARRED")

APPEAL_STATUSES = (
    "FILED",
    "SCHEDULED",
    "CONTINUED",
    "GRANTED",
    "DENIED",
    "DISMISSED",
)

DOCKET_STATUSES = ("OPEN", "CLOSED")

NOTICE_TYPES = (
    "APPROVAL",
    "DENIAL",
    "SUSPENSION",
    "REVOCATION",
    "RECOVERY_ASSESSMENT",
    "REFUND_DETERMINATION",
    "HEARING_DECISION",
)

# --- canonical addresses -------------------------------------------------
#
# Addresses are compared after upper-casing and whitespace collapsing, so the
# suite uses a small set of already-normalised literals.

ADDR_OAK = "100 OAK ST NORTHFIELD ST 10001"
ADDR_FARM = "200 FARM RD NORTHFIELD ST 10001"
ADDR_PINE = "300 PINE CT NORTHFIELD ST 10001"
ADDR_CEDAR = "400 CEDAR LN NORTHFIELD ST 10001"
ADDR_ELM = "999 ELM AVE SOUTHTON ST 10009"
