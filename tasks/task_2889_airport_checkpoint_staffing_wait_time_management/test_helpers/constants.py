"""Domain constants for the Airport Checkpoint Staffing API test suite.

Every value here is lifted verbatim from the PRD so that tests never restate a
magic number inline.
"""

# ── Roles (PRD §2.1) ──────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_CHECKPOINT_MANAGER = "CheckpointManager"
ROLE_STAFFING_PLANNER = "StaffingPlanner"
ROLE_DUTY_MANAGER = "DutyManager"
ROLE_SCREENING_OFFICER = "ScreeningOfficer"
ROLE_SUPERVISORY_OFFICER = "SupervisoryOfficer"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_CHECKPOINT_MANAGER,
    ROLE_STAFFING_PLANNER,
    ROLE_DUTY_MANAGER,
    ROLE_SCREENING_OFFICER,
    ROLE_SUPERVISORY_OFFICER,
]

OPAQUE_IDENTITY_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_CHECKPOINT_MANAGER,
    ROLE_STAFFING_PLANNER,
    ROLE_DUTY_MANAGER,
]

ENTITY_BACKED_ROLES = [ROLE_SCREENING_OFFICER, ROLE_SUPERVISORY_OFFICER]

# ── Logical clock (PRD §2.4) ──────────────────────────────────────────────────
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ── Pagination (PRD §2.3) ─────────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ── Time bands (PRD §2.6, §3.2) ───────────────────────────────────────────────
BAND_MINUTES = 30

# ── Lane capacity (PRD §3.2) ──────────────────────────────────────────────────
LANE_BASE_THROUGHPUT_PPH = {"STANDARD": 180, "EXPEDITED": 300}
LANE_BAND_CAPACITY = {"STANDARD": 90, "EXPEDITED": 150}
DEGRADED_EQUIPMENT_FACTOR = 0.80
SURGE_POSTURE_DERATE = 0.90
MIN_OPEN_LANES = {"STANDARD": 1, "EXPEDITED": 0}

# ── Money (PRD §3.3, §3.5) ────────────────────────────────────────────────────
OVERTIME_MULTIPLIER = 1.5
DETAIL_RATE_CENTS_PER_MINUTE = 100
ADMIN_FEE_TIER_1_MAX_EXCLUSIVE = 5000
ADMIN_FEE_TIER_1_RATE = "0.060"
ADMIN_FEE_TIER_2_MAX_EXCLUSIVE = 20000
ADMIN_FEE_TIER_2_RATE = "0.045"
ADMIN_FEE_TIER_3_RATE = "0.030"

ADMIN_FEE_RATE_DECIMALS = 3
WEIGHTED_AVERAGE_SECONDS_DECIMALS = 2
DIVERSION_RATE_DECIMALS = 4

# ── Wait publication (PRD §3.8) ───────────────────────────────────────────────
PUBLICATION_WINDOW_MINUTES = 20
MIN_SAMPLES_FOR_WEIGHTED_AVERAGE = 3
METHOD_WEIGHTS = {"BLE_SENSOR": 3, "MANUAL_TIMESTAMP": 2, "STAFF_ESTIMATE": 1}
ESCALATION_BREACH_COUNT_REQUIRED = 2

# ── Posture ladder (PRD §2.10) ────────────────────────────────────────────────
SURGE_OPEN_ESCALATION_THRESHOLD = 2
ELEVATED_OOS_LANE_THRESHOLD = 1

# ── Officer duty (PRD §3.7) ───────────────────────────────────────────────────
MAX_CONSECUTIVE_ON_POSITION_MINUTES = 60
REST_BUFFER_MINUTES = 15

# ── Throughput analytics (PRD §3.9) ───────────────────────────────────────────
THROUGHPUT_SHORTFALL_RATIO = 0.80
DIVERSION_RATE_DESIGN_THRESHOLD = 0.05
CONSECUTIVE_SHORTFALL_BANDS_REQUIRED = 2

# ── Equipment (PRD §3.1) ──────────────────────────────────────────────────────
REQUIRED_EQUIPMENT_BY_LANE_TYPE = {
    "STANDARD": ["WTMD", "AT_XRAY", "ADVANCED_IMAGING"],
    "EXPEDITED": ["WTMD", "AT_XRAY"],
}
EQUIPMENT_TYPES = ["WTMD", "AT_XRAY", "ADVANCED_IMAGING", "ETD", "CT"]
EQUIPMENT_STATES = ["SERVICEABLE", "DEGRADED", "OUT_OF_SERVICE"]

# ── Enumerations (PRD §3) ─────────────────────────────────────────────────────
CERTIFICATIONS = [
    "STANDARD_LANE",
    "EXPEDITED_LANE",
    "ADVANCED_IMAGING",
    "ETD_RESOLUTION",
    "SPECIAL_PROCEDURES",
    "SUPERVISOR",
]

LANE_TYPES = ["STANDARD", "EXPEDITED"]
LANE_STATES = ["CLOSED", "OPEN", "PAUSED", "DECOMMISSIONED"]
PAUSED_REASON_CODES = [
    "EQUIPMENT_FAULT",
    "STAFF_SHORTFALL",
    "LOW_DEMAND",
    "SECURITY_INCIDENT",
]

POSTURES = ["NORMAL", "ELEVATED", "SURGE", "SUSPENDED"]

DUTY_STATUSES = ["OFF_DUTY", "ON_DUTY", "ON_BREAK", "SEPARATED"]

CARRIER_TYPES = ["DOMESTIC", "INTERNATIONAL"]
SEASON_CODES = ["OFF_PEAK", "SHOULDER", "PEAK", "HOLIDAY"]
FLIGHT_STATUSES = ["SCHEDULED", "CANCELLED"]

FORECAST_VARIANTS = ["SCHEDULE_ONLY", "CURVE_BLENDED"]

PLAN_STATES = [
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "REJECTED",
    "ACTIVATED",
    "CLOSED",
    "SUPERSEDED",
]
REJECTION_REASON_CODES = ["COST", "COVERAGE", "CERTIFICATION_GAP", "POLICY"]
PLAN_COST_FIELDS = [
    "planned_regular_minutes",
    "planned_overtime_minutes",
    "base_cost_cents",
    "overtime_cost_cents",
    "detail_cost_cents",
    "subtotal_cents",
    "admin_fee_rate",
    "admin_fee_cents",
    "total_cost_cents",
]

ASSIGNMENT_STATES = [
    "SCHEDULED",
    "CHECKED_IN",
    "REASSIGN_PENDING",
    "RELEASED",
    "CANCELLED",
]
BREAK_STATES = ["NOT_DUE", "DUE", "ON_BREAK", "COMPLETED"]

MEASUREMENT_METHODS = ["BLE_SENSOR", "MANUAL_TIMESTAMP", "STAFF_ESTIMATE"]

TICKET_STATES = [
    "RAISED",
    "ACKNOWLEDGED",
    "RESOLVED_LANE_OPENED",
    "RESOLVED_DIVERTED",
    "EXPIRED",
]
TICKET_TRIGGER_REASONS = ["WAIT_THRESHOLD_BREACH", "POSTURE_DEGRADATION"]
TICKET_SCOPES = ["STANDARD", "EXPEDITED", "ALL"]

REFERRAL_REASONS = [
    "ALARM",
    "DISABILITY_ACCOMMODATION",
    "MEDICAL_DEVICE",
    "YOUNG_CHILD",
    "RANDOM",
]
PASSENGER_CATEGORIES = [
    "ADULT",
    "MINOR_UNDER_12",
    "WHEELCHAIR_USER",
    "MEDICAL_DEVICE_WEARER",
    "SERVICE_ANIMAL_HANDLER",
]
REFERRAL_STATES = [
    "RAISED",
    "IN_PROGRESS",
    "CLEARED",
    "REFERRED_LEO",
    "DENIED_ENTRY",
    "WITHDRAWN",
]

EVENT_CODES = ["HOLIDAY_PEAK", "SPORTING_EVENT", "CONVENTION", "IRREGULAR_OPS"]
DENIAL_REASON_CODES = ["BUDGET", "COVERAGE", "OFFICER_UNAVAILABLE"]
SURGE_DETAIL_STATES = ["REQUESTED", "APPROVED", "DENIED", "CANCELLED"]

DUTY_LEDGER_VARIANTS = ["FORWARD_LOOKING_PLANNED", "CHRONOLOGICAL_ACTUAL"]

# ── Common-field sets (PRD §2.4) ──────────────────────────────────────────────
# Most resources expose id, created_at, updated_at and version.
VERSIONED_COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]
# A show-up curve and a wait-time observation expose only id and created_at.
IMMUTABLE_COMMON_FIELDS = ["id", "created_at"]

# ── Not-found codes keyed by the path parameter they belong to (PRD §2.5) ──────
NOT_FOUND_CODE_BY_PARAM = {
    "checkpoint_id": "ERR_CHECKPOINT_NOT_FOUND",
    "lane_id": "ERR_LANE_NOT_FOUND",
    "equipment_unit_id": "ERR_EQUIPMENT_UNIT_NOT_FOUND",
    "officer_id": "ERR_OFFICER_NOT_FOUND",
    "show_up_curve_id": "ERR_SHOW_UP_CURVE_NOT_FOUND",
    "flight_schedule_entry_id": "ERR_FLIGHT_SCHEDULE_ENTRY_NOT_FOUND",
    "time_band_id": "ERR_TIME_BAND_NOT_FOUND",
    "staffing_plan_id": "ERR_STAFFING_PLAN_NOT_FOUND",
    "lane_assignment_id": "ERR_LANE_ASSIGNMENT_NOT_FOUND",
    "wait_time_observation_id": "ERR_WAIT_TIME_OBSERVATION_NOT_FOUND",
    "escalation_ticket_id": "ERR_ESCALATION_TICKET_NOT_FOUND",
    "screening_referral_id": "ERR_SCREENING_REFERRAL_NOT_FOUND",
    "surge_detail_id": "ERR_SURGE_DETAIL_NOT_FOUND",
}

# A syntactically valid UUID that is never minted by the server.
UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"
