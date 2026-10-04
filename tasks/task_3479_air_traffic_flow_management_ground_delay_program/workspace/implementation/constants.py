"""Shared constants for the ATFM implementation.

Every named constant carries its exact PRD value and is defined exactly once
here (PRD sections 2.6, 2.8, 3.2, 3.3, 3.5, 3.7; scaffold calculations table).
All other modules import from this module — no literalized duplicates.
"""

# --- Logical clock (PRD 2.5) ---
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Capacity forecast impact model (PRD 3.3 / calculations.capacity_forecast_rate) ---
WEATHER_IMPACT_STEP = 0.15
STAFFING_IMPACT_STEP = 0.10
EQUIPMENT_IMPACT_STEP = 0.05
REPORTED_EVENT_WEIGHT = 0.5
MIN_CAPACITY_FLOOR_PCT = 10

# --- RBS slot allocation (calculations.rbs_slot_allocation) ---
GA_QUOTA_PCT = 10
GA_MIN_RESERVED = 1

# --- Compression (calculations.compression_reallocation) ---
COMPRESSION_MAX_PASSES = 3

# --- Substitution (PRD 3.5) ---
SUBSTITUTION_MAX_SHIFT_MINUTES = 120

# --- CDM data freshness (PRD 2.6 rule 11) ---
FLIGHT_DATA_FRESHNESS_SECONDS = 3600

# --- Constraint events (PRD 3.2) ---
CONSTRAINT_EVENT_MAX_EXTENSIONS = 2

# --- Rate / field domains (PRD 3.1, 3.4) ---
GDP_RATE_MIN = 6
GDP_RATE_MAX = 60
AFP_RATE_MIN = 1
AFP_RATE_MAX = 60
FACILITY_BASE_RATE_MIN = 1
FACILITY_BASE_RATE_MAX = 120
SEVERITY_MIN = 1
SEVERITY_MAX = 5

# Valid GROUND_DELAY_PROGRAM rates: 6 <= r <= 60 with 3600 % r == 0.
GDP_VALID_RATES = tuple(
    r for r in range(GDP_RATE_MIN, GDP_RATE_MAX + 1) if 3600 % r == 0
)

EVENT_TYPE_STEPS = {
    "WEATHER": WEATHER_IMPACT_STEP,
    "STAFFING": STAFFING_IMPACT_STEP,
    "EQUIPMENT": EQUIPMENT_IMPACT_STEP,
}

# --- Roles (PRD 2.1) ---
ROLE_SYSTEM_ADMINISTRATOR = "SystemAdministrator"
ROLE_FLOW_MANAGER = "FlowManager"
ROLE_COMMAND_CENTER_ADMIN = "CommandCenterAdmin"
ROLE_OPERATOR = "Operator"
ROLES = (
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLE_FLOW_MANAGER,
    ROLE_COMMAND_CENTER_ADMIN,
    ROLE_OPERATOR,
)
ALL_ROLES = ROLES  # every declared role (all GET endpoints)

# --- Enum domains ---
FACILITY_TYPES = ("AIRPORT", "EN_ROUTE_SECTOR")
FACILITY_STATUSES = ("OPERATIONAL", "DEGRADED", "OUTAGE")
OPERATOR_TYPES = ("SCHEDULED_CARRIER", "GENERAL_AVIATION", "UNSCHEDULED_CHARTER")
EVENT_TYPES = ("WEATHER", "STAFFING", "EQUIPMENT")
FORECAST_VARIANTS = ("PLANNING", "OPERATIONAL")
TMI_TYPES = (
    "GROUND_DELAY_PROGRAM",
    "GROUND_STOP",
    "AIRSPACE_FLOW_PROGRAM",
    "REROUTE",
)
PRIORITY_CLASSES = ("HIGH_PRIORITY", "STANDARD")
GA_DECISIONS = ("ACCOMMODATE", "DENY")
FLIGHT_OPS_UPDATE_TARGETS = ("AIRBORNE", "LANDED")
