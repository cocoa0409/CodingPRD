"""Domain constants for the Streaming Encoding & Delivery Operations API.

Every literal here is transcribed from the PRD: role names (§2.1), the logical
clock's start instant (§2.5), enum value sets (§3), the numeric thresholds and
weights of the calculation rules (§3.1 - §3.9) and the pagination limits (§2.3).
"""

# --- Roles (§2.1) ----------------------------------------------------------
ROLE_CONTENT_OPS = "ContentOps"
ROLE_QC_ANALYST = "QcAnalyst"
ROLE_ENCODING_ENGINEER = "EncodingEngineer"
ROLE_DRM_OPERATOR = "DrmOperator"
ROLE_DELIVERY_ENGINEER = "DeliveryEngineer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_VENDOR_OPERATOR = "VendorOperator"

ALL_ROLES = [
    ROLE_CONTENT_OPS,
    ROLE_QC_ANALYST,
    ROLE_ENCODING_ENGINEER,
    ROLE_DRM_OPERATOR,
    ROLE_DELIVERY_ENGINEER,
    ROLE_PLATFORM_ADMIN,
    ROLE_VENDOR_OPERATOR,
]

# The six roles whose X-User-ID is an opaque operator identifier (§2.1).
OPAQUE_ROLES = [
    ROLE_CONTENT_OPS,
    ROLE_QC_ANALYST,
    ROLE_ENCODING_ENGINEER,
    ROLE_DRM_OPERATOR,
    ROLE_DELIVERY_ENGINEER,
    ROLE_PLATFORM_ADMIN,
]

# --- Logical clock (§2.5) --------------------------------------------------
INITIAL_CLOCK = "2026-08-01T00:00:00Z"
SWEEP_COUNTER_FIELDS = [
    "windows_activated",
    "windows_closed",
    "reservations_started",
    "reservations_ended",
    "jobs_completed",
    "jobs_failed",
    "titles_published",
    "titles_taken_down",
    "titles_expired",
]

# --- Identifiers that resolve to nothing (§2.4) ----------------------------
UUID_ABSENT = "11111111-1111-4111-8111-111111111111"
UUID_ABSENT_ALT = "22222222-2222-4222-8222-222222222222"

# --- Pagination (§2.3) -----------------------------------------------------
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 100
PAGINATION_META_FIELDS = ["page", "page_size", "total_count", "has_more"]

# --- Title (§2.9, §3.1) ----------------------------------------------------
CONTENT_TYPES = ["MOVIE", "EPISODE", "LIVE_EVENT"]
AVAILABILITY_STATES = ["DRAFT", "SCHEDULED", "PUBLISHED", "TAKEN_DOWN", "EXPIRED"]
PACKAGING_STATES = ["UNPACKAGED", "PACKAGING", "PACKAGED", "STALE"]
TAKEDOWN_REASONS = ["NONE", "MANUAL_LEGAL", "CONTRACT_END", "PACKAGING_STALE"]
DEFAULT_ENCODE_BUDGET_USD = 5000.00
PUBLICATION_GATE_CERTIFIED = 80.00
READINESS_WEIGHT_MASTER = 0.50
READINESS_WEIGHT_LADDER = 0.20
READINESS_WEIGHT_PACKAGE = 0.30

# --- MezzanineAsset / QC (§3.2) -------------------------------------------
QC_STATES = ["INGESTED", "QC_PASSED", "QC_FAILED", "REMEDIATION_REQUESTED", "QC_REJECTED"]
QC_VERDICTS = ["PASS", "WARN", "FAIL"]
BLOCKING_DEFECT_CODES = [
    "NONE",
    "ARTIFACT_BURST",
    "LOUDNESS_OUT_OF_SPEC",
    "CAPTION_MISSING",
    "MULTI_DEFECT",
]
FRAME_RATES = [23.976, 24.0, 25.0, 29.97, 50.0, 59.94]
LOUDNESS_TARGET_LUFS = -24.0
LOUDNESS_TOLERANCE_DB = 2.0
LOUDNESS_PENALTY_WEIGHT = 6.0
ARTIFACT_PENALTY_WEIGHT = 4.0
CAPTION_PENALTY_FLAT = 30.0
ARTIFACT_BURST_THRESHOLD = 8
LOUDNESS_BLOCKING_THRESHOLD_DB = 6.0
SEVERITY_BLOCKING_THRESHOLD = 40.0
ARTIFACT_WARN_THRESHOLD = 3
MAX_QC_ATTEMPTS = 3

# --- DeviceProfile / EncodingLadder (§3.3) --------------------------------
DEVICE_CLASSES = [
    "SMART_TV_4K",
    "SMART_TV_HD",
    "MOBILE_HIGH",
    "MOBILE_LOW",
    "SET_TOP_LEGACY",
    "BROWSER_HTML5",
]
TV_ONLY_CLASSES = ["SMART_TV_4K", "SMART_TV_HD", "SET_TOP_LEGACY"]
MOBILE_ONLY_CLASSES = ["MOBILE_HIGH", "MOBILE_LOW"]
CODEC_FAMILIES = ["H264", "HEVC", "AV1"]
DRM_SYSTEMS = ["WIDEVINE", "PLAYREADY", "FAIRPLAY"]
REQUIRED_DRM_SYSTEMS = ["WIDEVINE", "PLAYREADY", "FAIRPLAY", "NONE"]
DEVICE_PROFILE_STATES = ["ACTIVE", "RETIRED"]
LADDER_STATES = ["DRAFT", "VALIDATED", "LOCKED", "REJECTED", "SUPERSEDED"]
VALIDATION_REASON_CODES = [
    "NONE",
    "OK",
    "BITRATE_NOT_MONOTONIC",
    "DUPLICATE_HEIGHT",
    "NO_COMPATIBLE_DEVICE",
]
COVERAGE_TARGET_RUNGS = 5
FOUR_K_BONUS = 5.00
FOUR_K_BONUS_HEIGHT = 2160
DEVICE_COMPAT_SCORE_CAP = 100.00
MIN_RUNGS = 2
MAX_RUNGS = 8

# --- DrmPackage / EntitlementRule (§3.5) ----------------------------------
PACKAGE_STATES = ["PENDING", "PACKAGED", "STALE", "REVOKED"]
STALE_REASONS = ["NONE", "LADDER_SUPERSEDED", "CODEC_STANDARD_CHANGE"]
HDCP_LEVELS = ["NONE", "TYPE_0", "TYPE_1"]
HDCP_FLOOR_TYPE_1_HEIGHT = 2160
HDCP_FLOOR_TYPE_0_HEIGHT = 1080
SUBSCRIPTION_TIERS = ["BASIC", "STANDARD", "PREMIUM", "ANY"]
LICENSE_TIERS = ["BASIC", "STANDARD", "PREMIUM"]
DEVICE_CLASS_SCOPES = ["ALL", "TV_ONLY", "MOBILE_ONLY"]
DEFAULT_KEY_ROTATION_HOURS = 24
ENTITLEMENT_DECISIONS = ["ALLOW"]
ENTITLEMENT_REASON_CODES = ["MATCHED"]

# --- AvailabilityWindow (§3.6) --------------------------------------------
WINDOW_STATES = ["SCHEDULED", "ACTIVE", "CLOSED", "CANCELLED"]

# --- CdnVendor / RoutingPolicy / PlaybackMetricWindow (§3.7) --------------
VENDOR_STATES = ["ACTIVE", "DEGRADED", "DRAINED"]
STEERING_MODES = ["PERFORMANCE", "COST", "WEIGHTED"]
POLICY_STATES = ["ACTIVE", "STANDBY_ONLY", "UNROUTABLE"]
SELECTION_REASON_CODES = ["PERFORMANCE_RANK", "COST_RANK", "WEIGHTED_RANK", "NO_CANDIDATE"]
VENDOR_ELIGIBILITY_MIN_CONTRACT_HEALTH = 60.00
WEIGHTED_COMPOSITE_COST_WEIGHT = 1000.0
GB_PER_PLAY = 2.5
DEFAULT_PROJECTED_VOLUME_GB = 1000.00
SURCHARGE_RATE_LOW = 0.08
SURCHARGE_RATE_MID = 0.05
SURCHARGE_RATE_HIGH = 0.03
SURCHARGE_TIER_MID_FLOOR = 500.00
SURCHARGE_TIER_HIGH_FLOOR = 2000.00
WEIGHTED_SURCHARGE_ADDITION = 0.02
REBUFFER_WEIGHT = 2.5
STARTUP_WEIGHT = 1.5
ERROR_WEIGHT = 4.0
STARTUP_TARGET_MS = 2000
BREACH_THRESHOLD = 70.00
DEGRADE_THRESHOLD = 50.00
RECOVER_THRESHOLD = 75.00
DRAIN_BREACH_COUNT = 5
ROLLING_WINDOW_ROWS = 3
SEEDED_HEALTH_SCORE = 100.00

# --- LiveEventReservation (§3.8) ------------------------------------------
RESERVATION_STATES = ["RESERVED", "ARMED", "LIVE", "FAILED_OVER", "ENDED", "CANCELLED"]
DEFAULT_BUFFER_MINUTES = 15
MIN_BUFFER_MINUTES = 0
MAX_BUFFER_MINUTES = 60

# --- ReprocessJob (§3.9) --------------------------------------------------
JOB_STATES = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "ABORTED"]
TRIGGER_REASONS = [
    "CODEC_DEPRECATION",
    "STANDARD_UPDATE",
    "QUALITY_REGRESSION",
    "DEVICE_MATRIX_CHANGE",
]
ABORT_REASONS = ["NONE", "OPERATOR_ABORT", "ENCODE_FAILURE", "BUDGET_RECLAIM"]
CODEC_FACTORS = {"H264": 1.00, "HEVC": 1.35, "AV1": 2.10}
ENCODE_RATE_USD = 0.02
TRIGGER_REASON_WEIGHTS = {
    "CODEC_DEPRECATION": 40.0,
    "STANDARD_UPDATE": 30.0,
    "QUALITY_REGRESSION": 20.0,
    "DEVICE_MATRIX_CHANGE": 10.0,
}
PRIORITY_COST_CAP = 20.0

# --- Entities that carry updated_at and version (§2.4) --------------------
VERSIONED_ENTITIES = [
    "Title",
    "MezzanineAsset",
    "EncodingLadder",
    "DeviceProfile",
    "DrmPackage",
    "CdnVendor",
    "RoutingPolicy",
    "LiveEventReservation",
    "AvailabilityWindow",
    "ReprocessJob",
]

# --- The three immutable entities: id and created_at only (§2.4) ----------
IMMUTABLE_ENTITIES = ["QualityControlReport", "EntitlementRule", "PlaybackMetricWindow"]
