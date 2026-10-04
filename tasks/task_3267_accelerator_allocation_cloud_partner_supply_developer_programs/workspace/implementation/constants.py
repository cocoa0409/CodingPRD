"""Every numeric and enumerated constant, transcribed from SCAFFOLD.yaml.

Grouped by the calculation or rule that owns it so a reader can diff this file
against the scaffold without hunting.
"""

# ---------------------------------------------------------------- clock ----
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# ------------------------------------------------------------------ roles --
ROLES = (
    "PlatformAdmin",
    "SupplyPlanner",
    "PartnerProgramManager",
    "PartnerOps",
    "SupportAccountManager",
    "SupplyComplianceOfficer",
    "LifecycleProgramManager",
)

PARTNER_TYPE_SUPPORTS_BLUEPRINT_TYPE = {
    "CLOUD_PROVIDER": {"TRAINING_CLUSTER", "INFERENCE_SERVER", "EDGE_BOX", "WORKSTATION"},
    "SYSTEM_BUILDER": {"TRAINING_CLUSTER", "INFERENCE_SERVER", "EDGE_BOX", "WORKSTATION"},
    "ENTERPRISE_OEM": {"TRAINING_CLUSTER", "INFERENCE_SERVER", "EDGE_BOX", "WORKSTATION"},
    "EMBEDDED_VENDOR": {"EDGE_BOX", "INFERENCE_SERVER", "TRAINING_CLUSTER", "WORKSTATION"},
    "DIRECT_ENTERPRISE": {"INFERENCE_SERVER", "WORKSTATION", "TRAINING_CLUSTER", "EDGE_BOX"},
}

# ------------------------------------------------------- subscription fees --
TIER_SEAT_FEE = {"BASIC": 12000, "BUSINESS": 36000, "ENTERPRISE": 90000}
SEAT_MIN = 40
SEAT_CAP = 1000
CREDIT_BELOW_MIN = 3
CREDIT_AT_OR_ABOVE_MIN = 5

# -------------------------------------------------------------- allocation --
TIER_INDEX = {"COOL": 0, "WARM": 1, "HOT": 2, "SCALDING": 3}
W_TIME = 10.0
W_UNIT = 1.0
TIME_MAX = 30
UNIT_MAX = 500
PENALTY_ATTEMPT = 5.0

COMMITMENT_RATE_TABLE = {"SHORT": 0.2, "MEDIUM": 0.35, "LONG": 0.5}
CENT_SCALE = 100

# ------------------------------------------------------------------ ledger --
# The committed-volume ceiling: requested quantity must not exceed the
# partner's held entitlement units plus this configured headroom (the
# committed-volume term appears on both sides of the comparison and cancels).
SUPPLY_CEILING_HEADROOM_UNITS = 1000
ENTITLEMENT_CEILING_UNITS = 100000

# ---------------------------------------------------------- rate / pricing --
RATE_PER_UNIT = 1.75
RATE_BAND_WIDTH_UNITS = 100
RATE_BAND_STEP = 0.25
RATE_CAP = 4.5
CUTOVER_EPOCH_INDEX = 3

# ------------------------------------------------------------ pool hotness --
HOTNESS_WARM_RATE = 2.0
HOTNESS_HOT_RATE = 7.0
HOTNESS_SCALDING_RATE = 10.5
HALF_LIFE_EPOCHS = 3
BAND_CEILING = {"COOL": "COOL", "WARM": "COOL", "HOT": "WARM", "SCALDING": "COOL"}
FRICTION_HOLD_RELEASE_SCORE = 4.0
FRICTION_BINDING_MAX_SCORE = 4.0
SCORE_BASE = 1.0

# ------------------------------------------------------------- export gates --
DENSITY_BOUNDARY = 1400
DENSITY_STEP = 100
DESTINATION_COUNTRIES = ("US", "DE", "FR", "CN", "SG", "CA")
PROHIBITED_DESTINATIONS = ("CN",)
# Destinations classed TIER_2_LICENSE_REQUIRED, i.e. those an export licence
# grant may unlock (PRD 2.5 names DE, FR, SG and CA).
LICENSE_REQUIRED_DESTINATIONS = ("DE", "FR", "SG", "CA")

# ------------------------------------------------------------ forecasting --
FORECAST_BOUNDARY_DAY = 15
SHORT_DEADLINE_OFFSET_DAYS = 1
MEDIUM_GAP_DAYS = 45
LONG_GAP_DAYS = 90
FORFEIT_BAND_RATE = {"SHORT": 0.1, "MEDIUM": 0.25, "LONG": 0.25}
FORFEIT_OVERAGE_PENALTY = 0.05
OVERAGE_CAP = 0.75
NOTICE_DAYS = {"SHORT": 14, "MEDIUM": 30, "LONG": 60}

# ------------------------------------------------------------- evaluation --
EVAL_RESERVE_RATIO = 0.1
LATE_FEE_PER_DAY_UNITS = 0.5
LATE_FEE_CAP_UNITS = 15.0

# ------------------------------------------------------------- membership --
MEMBERSHIP_GRACE_DAYS = 30
TIER_ORDER = ("COMMUNITY", "REGISTERED", "PREFERRED", "ELITE")
TIER_KIT_UNITS = {"COMMUNITY": 0, "REGISTERED": 2, "PREFERRED": 6, "ELITE": 12}
TIER_INCIDENT_UNITS = {"COMMUNITY": 0, "REGISTERED": 1, "PREFERRED": 3, "ELITE": 8}
ELITE_ADVANCE_MINUTES = 600
PREVIEW_GRANT_SPAN_DAYS = 60
PREVIEW_GRANT_BUFFER_DAYS = 30

# -------------------------------------------------------------- lifecycle --
LIFECYCLE_GRACE_DAYS = 365
EMBEDDED_EXTENSION_DAYS = 730
COMMITMENT_FLOOR_MIN_DAYS = 1825

# --------------------------------------------------------- partner priority --
TIER1_ENTITLEMENT_MIN = 2000
TIER1_ON_TIME_RATIO_MIN = 0.8
TIER2_ENTITLEMENT_MIN = 500
ATTEMPT_PENALTY_BASE = 5
ATTEMPT_PENALTY_CAP = 20

# ------------------------------------------------------- lifecycle stage set --
LIFECYCLE_STAGES = ("PREVIEW", "GENERAL_AVAILABILITY", "MATURE", "END_OF_LIFE")
MATURE_STAGES = ("MATURE", "END_OF_LIFE")

# ------------------------------------------------------------- enum members --
PARTNER_TYPES = (
    "CLOUD_PROVIDER",
    "SYSTEM_BUILDER",
    "ENTERPRISE_OEM",
    "EMBEDDED_VENDOR",
    "DIRECT_ENTERPRISE",
)
EXPORT_RESTRICTION_TIERS = ("LICENSE_EXCEPTION", "LICENSE_REQUIRED", "PROHIBITED")
QUALIFICATION_STATUSES = ("APPLIED", "IN_VALIDATION", "QUALIFIED", "REJECTED", "SUSPENDED")
PARTNER_STANDING = ("ACTIVE", "SUSPENDED", "TERMINATED")
PRIORITY_CLASSES = ("TIER_1", "TIER_2", "TIER_3", "UNQUALIFIED")
PRODUCT_FAMILIES = ("DATACENTER", "WORKSTATION", "EMBEDDED", "CONSUMER")
FORM_FACTORS = ("SXM", "PCLE", "MCM")
NODE_REGIONS = ("AMERICAS", "EMEA", "APAC")
HOTNESS_TIERS = ("COOL", "WARM", "HOT", "SCALDING")
NODE_STAGES = ("OPEN", "FRICTION_HOLD", "DRAINING", "BINDING")
BLUEPRINT_TYPES = ("TRAINING_CLUSTER", "INFERENCE_SERVER", "EDGE_BOX", "WORKSTATION")
BLUEPRINT_STATUSES = ("DRAFT", "CERTIFIED", "RETIRED")
EVIDENCE_STATUSES = ("SUBMITTED", "ACCEPTED", "REJECTED")
HOLD_STATES = ("REQUESTED", "COMMITTED", "CANCELLED", "RECLAIMED", "EXPIRED")
ECONOMIC_TAGS = ("LOW_VALUE", "HIGH_VALUE")
SUPPORT_TIERS = ("BASIC", "BUSINESS", "ENTERPRISE")
SUBSCRIPTION_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "RECLAIMED", "EXPIRED")
DEPLOYMENT_STATES = ("PENDING", "ACTIVATED", "TERMINATED")
EXPORT_CLASSES = ("TIER_1_CLEARED", "TIER_2_LICENSE_REQUIRED", "TIER_3_PROHIBITED")
STACK_STATES = ("DRAFT", "RELEASED", "RETIRED")
MEMBERSHIP_STATUSES = ("REQUESTED", "UNDER_EVALUATION", "ACTIVE", "LAPSED", "REVOKED")
GRANT_STATUSES = ("OPEN", "FULFILLED", "REVOKED", "EXPIRED")
ACK_STATUSES = ("BOUND", "FULFILLED")
FORECAST_TRACKING = ("DRAFT", "FORECAST_SUBMITTED", "ACTIVE", "COMMITTED", "CANCELLED")
HORIZON_BANDS = ("SHORT", "MEDIUM", "LONG")
LOAN_STATES = ("REQUESTED", "APPROVED", "ACTIVE", "RETURNED", "RECLAIMED", "OVERDUE")
MILESTONE_TYPES = ("KICKOFF", "BENCHMARK", "INTEGRATION", "ACCEPTANCE")
MILESTONE_RESULTS = ("PASSED", "FAILED", "INCONCLUSIVE")
MILESTONE_STATES = ("OPEN", "RECORDED", "LATE")
COMMITMENT_STATUSES = ("REQUESTED", "GRANTED", "DECLINED")
PENALTY_REASONS = ("BAND_VIOLATION", "LATE_CANCEL")
PENALTY_STATES = ("ACTIVE", "DECAYED", "SETTLED")
EPOCH_STATUSES = ("OPEN", "CLOSED")
CONTRACT_STATUSES = ("OPEN", "CLOSED")
GRANT_LICENSE_STATUSES = ("ACTIVE", "REVOKED")

# ------------------------------------------------------- pagination bounds --
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0