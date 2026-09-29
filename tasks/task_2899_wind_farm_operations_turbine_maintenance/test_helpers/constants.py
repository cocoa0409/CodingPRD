"""Domain constants: enum value sets, role names, clock origin and derived-figure
constants that the API contract fixes as literals.
"""

API_PREFIX = "/wind-ops"

# --- Roles ------------------------------------------------------------------
ROLE_SITE_ADMIN = "SiteAdmin"
ROLE_CONTROL_ROOM_OPERATOR = "ControlRoomOperator"
ROLE_MAINTENANCE_PLANNER = "MaintenancePlanner"
ROLE_RELIABILITY_ENGINEER = "ReliabilityEngineer"
ROLE_CREW_LEAD = "CrewLead"
ROLE_COMMERCIAL_MANAGER = "CommercialManager"

ALL_ROLES = [
    ROLE_SITE_ADMIN,
    ROLE_CONTROL_ROOM_OPERATOR,
    ROLE_MAINTENANCE_PLANNER,
    ROLE_RELIABILITY_ENGINEER,
    ROLE_CREW_LEAD,
    ROLE_COMMERCIAL_MANAGER,
]

UNDECLARED_ROLE = "TurbineTechnicianIntern"

# --- Clock ------------------------------------------------------------------
#: The logical clock's declared starting instant.
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# --- Turbine dimensions -----------------------------------------------------
AVAILABILITY_ONLINE = "ONLINE"
AVAILABILITY_FAULTED = "FAULTED"
AVAILABILITY_DOWN_DISPATCH = "DOWN_DISPATCH"
AVAILABILITY_DOWN_SERVICE = "DOWN_SERVICE"
AVAILABILITY_DOWN_MAJOR = "DOWN_MAJOR"
AVAILABILITY_DECOMMISSIONED = "DECOMMISSIONED"

CURTAILMENT_UNCONSTRAINED = "UNCONSTRAINED"
CURTAILMENT_CURTAILED = "CURTAILED"
CURTAILMENT_FORCED_STOP = "FORCED_STOP"

# --- Work orders ------------------------------------------------------------
WORK_TYPE_SCHEDULED_SERVICE = "SCHEDULED_SERVICE"
WORK_TYPE_FAULT_DISPATCH = "FAULT_DISPATCH"
WORK_TYPE_BLADE_REPAIR = "BLADE_REPAIR"
WORK_TYPE_MAJOR_COMPONENT = "MAJOR_COMPONENT"

WO_DRAFT = "DRAFT"
WO_SUBMITTED = "SUBMITTED"
WO_REVISION_REQUESTED = "REVISION_REQUESTED"
WO_SCHEDULED = "SCHEDULED"
WO_IN_PROGRESS = "IN_PROGRESS"
WO_COMPLETED = "COMPLETED"
WO_CANCELLED = "CANCELLED"

#: A work order may be sent back for revision only while its revision round is
#: strictly below this bound.
MAX_REVISION_ROUNDS = 3

#: Inclusive slack (in operating hours) below the service-due figure at which a
#: scheduled-service order may already be raised.
SERVICE_DUE_SLACK_HOURS = 200

# --- Certifications ---------------------------------------------------------
CERT_GWO_BASIC = "GWO_BASIC"
CERT_ROPE_ACCESS = "ROPE_ACCESS"
CERT_HV_SWITCHING = "HV_SWITCHING"
CERT_CRANE_BANKSMAN = "CRANE_BANKSMAN"
CERT_BLADE_COMPOSITE = "BLADE_COMPOSITE"

# --- Crews ------------------------------------------------------------------
CREW_AVAILABLE = "AVAILABLE"
CREW_ON_SHIFT = "ON_SHIFT"
CREW_OFF_ROTATION = "OFF_ROTATION"

# --- Fault codes ------------------------------------------------------------
SEVERITY_ADVISORY = "ADVISORY"
SEVERITY_RESETTABLE = "RESETTABLE"
SEVERITY_LOCKOUT = "LOCKOUT"

TRIAGE_RAISED = "RAISED"
TRIAGE_RESET_PENDING = "RESET_PENDING"
TRIAGE_DISPATCH_REQUIRED = "DISPATCH_REQUIRED"
TRIAGE_DISPATCHED = "DISPATCHED"
TRIAGE_CLEARED = "CLEARED"
TRIAGE_CLOSED = "CLOSED"

DISPOSITION_REMOTE_RESET = "REMOTE_RESET"
DISPOSITION_DISPATCH = "DISPATCH"

RESET_OUTCOME_SUCCEEDED = "SUCCEEDED"
RESET_OUTCOME_FAILED = "FAILED"

#: Rolling window length, in hours, of the remote-reset counter.
RESET_WINDOW_HOURS = 24

#: Weighted severity contributions to the work-order priority score.
PRIORITY_SEVERITY_MAJOR_COMPONENT = 1.00
PRIORITY_SEVERITY_LOCKOUT = 0.90
PRIORITY_SEVERITY_RESETTABLE = 0.60
PRIORITY_SEVERITY_ADVISORY = 0.20
PRIORITY_SEVERITY_SCHEDULED_SERVICE = 0.30

# --- Weather windows --------------------------------------------------------
WINDOW_FORECAST = "FORECAST"
WINDOW_CONFIRMED = "CONFIRMED"
WINDOW_CONSUMED = "CONSUMED"
WINDOW_EXPIRED = "EXPIRED"

# --- Blade findings ---------------------------------------------------------
INSPECTION_DRONE = "DRONE"
INSPECTION_ROPE_ACCESS = "ROPE_ACCESS"
INSPECTION_GROUND_OPTICAL = "GROUND_OPTICAL"

DAMAGE_LEADING_EDGE_EROSION = "LEADING_EDGE_EROSION"
DAMAGE_CRACK_TRANSVERSE = "CRACK_TRANSVERSE"
DAMAGE_LIGHTNING_STRIKE = "LIGHTNING_STRIKE"
DAMAGE_DELAMINATION = "DELAMINATION"

#: Damage-type weighting factors used by the blade severity score.
DAMAGE_TYPE_FACTORS = {
    DAMAGE_LEADING_EDGE_EROSION: 0.30,
    DAMAGE_CRACK_TRANSVERSE: 1.00,
    DAMAGE_LIGHTNING_STRIKE: 0.70,
    DAMAGE_DELAMINATION: 0.85,
}

BLADE_OPEN = "OPEN"
BLADE_PRIORITIZED = "PRIORITIZED"
BLADE_REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
BLADE_REPAIRED = "REPAIRED"
BLADE_WAIVED = "WAIVED"

BAND_CRITICAL = "CRITICAL"
BAND_HIGH = "HIGH"
BAND_MEDIUM = "MEDIUM"
BAND_LOW = "LOW"

#: Band lower bounds and their repair-due allowances, in days.
BAND_CRITICAL_MIN = 80
BAND_HIGH_MIN = 60
BAND_MEDIUM_MIN = 40
REPAIR_DUE_DAYS = {
    BAND_CRITICAL: 14,
    BAND_HIGH: 45,
    BAND_MEDIUM: 120,
    BAND_LOW: 365,
}

# --- Spare parts ------------------------------------------------------------
COMPONENT_GEARBOX = "GEARBOX"
COMPONENT_BLADE = "BLADE"
COMPONENT_GENERATOR = "GENERATOR"

STOCK_IN_STOCK = "IN_STOCK"
STOCK_BELOW_REORDER_POINT = "BELOW_REORDER_POINT"
STOCK_OUT_OF_STOCK = "OUT_OF_STOCK"

# --- Cranes -----------------------------------------------------------------
CRANE_CRAWLER_600T = "CRAWLER_600T"
CRANE_TOWER_ASSIST = "TOWER_ASSIST"
CRANE_SELF_ERECTING = "SELF_ERECTING"

CRANE_REQUESTED = "REQUESTED"
CRANE_MOBILIZED = "MOBILIZED"
CRANE_DEMOBILIZED = "DEMOBILIZED"
CRANE_CANCELLED = "CANCELLED"

#: Padding, in hours, applied to each side of a mobilization span before the
#: buffer comparison.
CRANE_BUFFER_HOURS = 48

#: Lift hours absorbed by a single crane lift day.
LIFT_HOURS_PER_DAY = 10

#: Volume-credit tiers keyed on the crane subtotal, in cents.
CRANE_CREDIT_TIER_1_FLOOR = 5000000
CRANE_CREDIT_TIER_2_FLOOR = 15000000
CRANE_CREDIT_RATE_TIER_0 = 0.00
CRANE_CREDIT_RATE_TIER_1 = 0.03
CRANE_CREDIT_RATE_TIER_2 = 0.06

#: Share of the mobilization fee charged when a mobilization is cancelled.
CRANE_CANCELLATION_FEE_SHARE = 0.40

# --- Component replacements -------------------------------------------------
REPLACEMENT_PLANNED = "PLANNED"
REPLACEMENT_CRANE_RESERVED = "CRANE_RESERVED"
REPLACEMENT_UPTOWER_READY = "UPTOWER_READY"
REPLACEMENT_EXECUTED = "EXECUTED"
REPLACEMENT_CLOSED = "CLOSED"
REPLACEMENT_CANCELLED = "CANCELLED"

PATH_CRANE_LIFT = "CRANE_LIFT"
PATH_UPTOWER_REPAIR = "UPTOWER_REPAIR"

#: Cost, in cents, charged per up-tower labour hour on execution.
UPTOWER_LABOR_RATE_CENTS_PER_HOUR = 950000

# --- Curtailment ------------------------------------------------------------
CURTAILMENT_REASON_GRID = "GRID"
CURTAILMENT_REASON_NOISE = "NOISE"
CURTAILMENT_REASON_ICING = "ICING"
CURTAILMENT_REASON_WILDLIFE = "WILDLIFE"

CURTAILMENT_PENDING = "PENDING"
CURTAILMENT_ACTIVE = "ACTIVE"
CURTAILMENT_RELEASED = "RELEASED"
CURTAILMENT_CANCELLED = "CANCELLED"

#: Maximum number of curtailment orders a turbine may hold active at once.
CURTAILMENT_STACK_LIMIT = 2

# --- Service agreements -----------------------------------------------------
BASIS_TIME_BASED = "TIME_BASED"
BASIS_ENERGY_BASED = "ENERGY_BASED"

AGREEMENT_ACTIVE = "ACTIVE"
AGREEMENT_IN_SETTLEMENT = "IN_SETTLEMENT"
AGREEMENT_SETTLED = "SETTLED"

# --- Landowner settlements --------------------------------------------------
ROYALTY_METERED_ONLY = "METERED_ONLY"
ROYALTY_DEEMED_INCLUSIVE = "DEEMED_INCLUSIVE"

SETTLEMENT_DRAFT = "DRAFT"
SETTLEMENT_APPROVED = "APPROVED"
SETTLEMENT_VOID = "VOID"

# --- Pagination -------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
