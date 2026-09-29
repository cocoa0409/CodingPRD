"""Business constants for the audio post-production API test suite.

Every value here is taken from the product requirements document: role names,
enum members, defaults, facility rates and the pinned thresholds used by the
billing roll-up, the licence-risk scores and the QC verdict.
"""

# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------

ROLE_FACILITY_ADMIN = "FacilityAdmin"
ROLE_POST_SUPERVISOR = "PostSupervisor"
ROLE_SOUND_EDITOR = "SoundEditor"
ROLE_MIXER = "Mixer"
ROLE_QC_OPERATOR = "QcOperator"
ROLE_CLIENT_REVIEWER = "ClientReviewer"

ALL_ROLES = (
    ROLE_FACILITY_ADMIN,
    ROLE_POST_SUPERVISOR,
    ROLE_SOUND_EDITOR,
    ROLE_MIXER,
    ROLE_QC_OPERATOR,
    ROLE_CLIENT_REVIEWER,
)

# --------------------------------------------------------------------------
# Opaque operator identifiers used across the suite
# --------------------------------------------------------------------------

ADMIN_USER_ID = "admin-1"
SUPERVISOR_USER_ID = "sup-1"
SUPERVISOR_TWO_USER_ID = "sup-2"
EDITOR_USER_ID = "editor-1"
QC_ONE_USER_ID = "qc-1"
QC_TWO_USER_ID = "qc-2"
CLIENT_USER_ID = "client-user-1"
OTHER_CLIENT_USER_ID = "client-user-2"

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

CLOCK_DEFAULT_INSTANT = "2026-08-01T00:00:00Z"
INSTANT_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
ENVELOPE_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Enum members
# --------------------------------------------------------------------------

PLATFORMS = ("THEATRICAL", "BROADCAST", "STREAMING", "INTERNATIONAL_ME")
CHANNEL_LAYOUTS = ("STEREO", "5_1", "7_1", "ATMOS")
STEM_LAYOUTS = ("STEREO", "5_1", "7_1", "ATMOS")
TURNAROUND_CLASSES = ("STANDARD", "EXPEDITED", "RUSH")
UNION_STATUSES = ("UNION", "NON_UNION")
ASSET_KINDS = ("SFX", "FOLEY", "MUSIC_LIBRARY")
LICENSE_TYPES = ("ROYALTY_FREE", "RIGHTS_MANAGED")
TERRITORY_SCOPES = ("WORLDWIDE", "DOMESTIC")
CUE_SOURCES = ("COMPOSER_ORIGINAL", "LIBRARY")
BOOKING_TYPES = ("PREMIX", "FINAL_MIX", "PRINTMASTER")
CLIENT_ATTENDANCE_VALUES = ("ONSITE", "REMOTE", "NONE")

PICTURE_STATUSES = ("NOT_LOCKED", "LOCKED", "LOCK_BROKEN")
PIPELINE_STAGES = (
    "INTAKE",
    "EDITORIAL",
    "PREMIX",
    "FINAL_MIX",
    "QC",
    "DELIVERED",
    "ARCHIVED",
)
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")

DELIVERABLE_OPEN_STATUSES = (
    "PREPARED",
    "QC_SUBMITTED",
    "QC_REJECTED",
    "REMEDIATION",
    "QC_PASSED",
)
BOOKING_OCCUPANCY_STATUSES = ("RESERVED", "CONFIRMED", "IN_PROGRESS", "COMPLETED")

QC_VERDICT_PASS = "PASS"
QC_VERDICT_FAIL = "FAIL"

CODE_LOUDNESS_OUT_OF_TOLERANCE = "LOUDNESS_OUT_OF_TOLERANCE"
CODE_TRUE_PEAK_EXCEEDED = "TRUE_PEAK_EXCEEDED"
CODE_ME_STEMS_MISSING = "ME_STEMS_MISSING"
REJECTION_CODE_ORDER = (
    CODE_LOUDNESS_OUT_OF_TOLERANCE,
    CODE_TRUE_PEAK_EXCEEDED,
    CODE_ME_STEMS_MISSING,
)

STALE_REASON_PICTURE_LOCK_BROKEN = "PICTURE_LOCK_BROKEN"
STALE_REASON_CUE_REVISED = "CUE_REVISED"
STALE_REASON_LICENSE_REVOKED = "LICENSE_REVOKED"

INVALIDATION_REASON_STEM_STALE = "STEM_STALE"
RELEASE_REASON_DELIVERABLE_INVALIDATED = "DELIVERABLE_INVALIDATED"

UNLICENSED_REASON_ASSET_REVOKED = "ASSET_REVOKED"
UNLICENSED_REASON_ASSET_EXPIRED = "ASSET_EXPIRED"
UNLICENSED_REASON_TERRITORY_OUT_OF_SCOPE = "TERRITORY_OUT_OF_SCOPE"

CANCELLATION_REASON_CLIENT_REQUEST = "CLIENT_REQUEST"
CANCELLATION_REASON_SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
CANCELLATION_REASON_TALENT_NO_SHOW = "TALENT_NO_SHOW"

# --------------------------------------------------------------------------
# Field defaults declared by the specification
# --------------------------------------------------------------------------

DEFAULT_REQUIRES_ME_STEMS = False
DEFAULT_MAX_REMEDIATION_ROUNDS = 2
DEFAULT_QC_TURNAROUND_HOURS = 24
DEFAULT_SUPPORTS_REMOTE_REVIEW = False
DEFAULT_CHANGEOVER_MINUTES = 45
DEFAULT_MAX_DAILY_HOURS = 10.00
DEFAULT_DAILY_CAP_MINUTES = 240
DEFAULT_MIN_CALL_MINUTES = 60
DEFAULT_TURNAROUND_CLASS = "STANDARD"
DEFAULT_STAGE_HOURS_AUTHORIZED = 40.00
DEFAULT_CLIENT_ATTENDANCE = "NONE"
DEFAULT_INCLUDES_ME_STEMS = False
DEFAULT_RETENTION_YEARS = 10

# --------------------------------------------------------------------------
# Facility rates and pinned thresholds
# --------------------------------------------------------------------------

CONFORM_RATE_CENTS_PER_STEM_MINUTE = 1500

UNION_RATE_CENTS_PER_MINUTE = 900
NON_UNION_RATE_CENTS_PER_MINUTE = 600

MIN_SESSION_HOURS = 2.00
QUARTER_HOUR = 0.25
OVERTIME_FACTOR = 1.5

TURNAROUND_MULTIPLIERS = {"STANDARD": 1.00, "EXPEDITED": 1.25, "RUSH": 1.60}
RUSH_SURCHARGE_RATES = {"STANDARD": 0.00, "EXPEDITED": 0.10, "RUSH": 0.20}

VOLUME_DISCOUNT_TIER_ONE_MAX = 499999
VOLUME_DISCOUNT_TIER_TWO_MIN = 500000
VOLUME_DISCOUNT_TIER_TWO_MAX = 999999
VOLUME_DISCOUNT_TIER_THREE_MIN = 1000000
VOLUME_DISCOUNT_RATES = {"TIER_ONE": 0.00, "TIER_TWO": 0.05, "TIER_THREE": 0.08}

LICENSE_BILLABLE_UNIT_SECONDS = 30
RISK_WEIGHT_RIGHTS_MANAGED = 20
RISK_WEIGHT_ROYALTY_FREE = 5
RISK_WEIGHT_UNLICENSED_PENALTY = 30
RISK_WEIGHT_NEAR_EXPIRY = 10
RISK_NEAR_EXPIRY_WINDOW_DAYS = 30
RISK_SCORE_CAP = 100.00
RISK_BLOCK_THRESHOLD = 50.00

# --------------------------------------------------------------------------
# Tolerances
# --------------------------------------------------------------------------

DECIMAL_TOLERANCE = 0.01

# --------------------------------------------------------------------------
# A syntactically valid identifier that resolves to no record
# --------------------------------------------------------------------------

UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
