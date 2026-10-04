"""Business constants declared by the Air Traffic Flow Management API contract.

Every value in this module is a literal the PRD states. Tests import these
instead of re-typing magic numbers, so a boundary case such as "the third
extension attempt" reads as the rule it exercises. Nothing else belongs here:
scenario conveniences (the recipe clock pin, canonical facility idents) live in
``fixtures.py`` / ``factories.py``.
"""

# ── Logical clock (PRD §2.5) ───────────────────────────────────────────────
# Before any client has set it, the logical clock reads exactly this instant
# and must never fall back to wall-clock time.
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

# ── Roles (PRD §2.1) ───────────────────────────────────────────────────────
# Exactly four roles exist, spelled precisely as follows.
ROLE_SYSTEM_ADMINISTRATOR = "SystemAdministrator"
ROLE_FLOW_MANAGER = "FlowManager"
ROLE_COMMAND_CENTER_ADMIN = "CommandCenterAdmin"
ROLE_OPERATOR = "Operator"

ALL_ROLES = (
    ROLE_SYSTEM_ADMINISTRATOR,
    ROLE_FLOW_MANAGER,
    ROLE_COMMAND_CENTER_ADMIN,
    ROLE_OPERATOR,
)

# ── Pagination envelope (PRD §2.3) ─────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Facilities (PRD §3.1) ──────────────────────────────────────────────────
# base_acceptance_rate is an integer from 1 to 120 inclusive.
FACILITY_MIN_BASE_ACCEPTANCE_RATE = 1
FACILITY_MAX_BASE_ACCEPTANCE_RATE = 120

# ── Constraint events (PRD §3.2) ───────────────────────────────────────────
# severity is an integer from 1 to 5 inclusive, 5 worst; the hard cap on
# extensions per event is CONSTRAINT_EVENT_MAX_EXTENSIONS.
SEVERITY_MIN = 1
SEVERITY_MAX = 5
CONSTRAINT_EVENT_MAX_EXTENSIONS = 2

# ── Capacity forecasting (PRD §3.3) ────────────────────────────────────────
# Each included event contributes (1 - step * severity * weight); CONFIRMED
# events weigh 1.0, REPORTED events weigh REPORTED_EVENT_WEIGHT and enter only
# the OPERATIONAL variant; the effective multiplier never drops below
# MIN_CAPACITY_FLOOR_PCT percent.
WEATHER_IMPACT_STEP = 0.15
STAFFING_IMPACT_STEP = 0.10
EQUIPMENT_IMPACT_STEP = 0.05
REPORTED_EVENT_WEIGHT = 0.5
MIN_CAPACITY_FLOOR_PCT = 10

IMPACT_STEP_BY_EVENT_TYPE = {
    "WEATHER": WEATHER_IMPACT_STEP,
    "STAFFING": STAFFING_IMPACT_STEP,
    "EQUIPMENT": EQUIPMENT_IMPACT_STEP,
}

# ── Initiative rate shapes (PRD §3.4) ──────────────────────────────────────
# GROUND_DELAY_PROGRAM: integer in [6, 60] with 3600 exactly divisible by it.
# AIRSPACE_FLOW_PROGRAM: integer in [1, 60]. GROUND_STOP: exactly 0.
# REROUTE: ignored, stored as 0. When omitted, controlled_rate defaults to 0.
GDP_MIN_CONTROLLED_RATE = 6
GDP_MAX_CONTROLLED_RATE = 60
GDP_RATE_DIVISOR = 3600
AFP_MIN_CONTROLLED_RATE = 1
AFP_MAX_CONTROLLED_RATE = 60
GROUND_STOP_CONTROLLED_RATE = 0
DEFAULT_CONTROLLED_RATE = 0

# ── Ration-by-schedule GA reservation (PRD §3.4) ───────────────────────────
# reserved_slots = max(GA_MIN_RESERVED, floor(slot_count * GA_QUOTA_PCT / 100));
# the last reserved_slots slots carry is_ga_reserved.
GA_QUOTA_PCT = 10
GA_MIN_RESERVED = 1

# ── Flights, substitution, compression (PRD §3.5) ──────────────────────────
# Substitution requires both flights' last_eta_reported_at within
# FLIGHT_DATA_FRESHNESS_SECONDS of the logical clock, and neither flight may be
# shifted more than SUBSTITUTION_MAX_SHIFT_MINUTES from its scheduled_arrival.
FLIGHT_DATA_FRESHNESS_SECONDS = 3600
SUBSTITUTION_MAX_SHIFT_MINUTES = 120
COMPRESSION_MAX_PASSES = 3

# ── GA accommodation (PRD §3.7) ────────────────────────────────────────────
# An accommodated request's flight gets a server-minted designator: the prefix
# "GA-" followed by the first eight characters of the request's id.
GA_DESIGNATOR_PREFIX = "GA-"
GA_DESIGNATOR_ID_CHARS = 8
