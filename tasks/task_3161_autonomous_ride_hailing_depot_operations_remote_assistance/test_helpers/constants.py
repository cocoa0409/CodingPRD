"""Domain constants: numeric thresholds from the credit, readiness, posture,
retention and SLA arithmetic plus the enum vocabulary of the fleet interface.

Keep this module free of behaviour — it exists so no test hard-codes a
threshold inline and so every expected literal can be recomputed from the
PRD prose.
"""

import math

API_PREFIX = "/fleet"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Enumerations (PRD section 2 and section 3 vocabulary) ────────────────

ROLE_FLEET_OPERATIONS = "FleetOperations"
ROLE_DEPOT_TECHNICIAN = "DepotTechnician"
ROLE_REMOTE_ASSISTANCE_OPERATOR = "RemoteAssistanceOperator"
ROLE_TERRITORY_PLANNER = "TerritoryPlanner"
ROLE_SAFETY_REVIEWER = "SafetyReviewer"
ROLE_MAPPING_ENGINEER = "MappingEngineer"

ALL_ROLES = (
    ROLE_FLEET_OPERATIONS,
    ROLE_DEPOT_TECHNICIAN,
    ROLE_REMOTE_ASSISTANCE_OPERATOR,
    ROLE_TERRITORY_PLANNER,
    ROLE_SAFETY_REVIEWER,
    ROLE_MAPPING_ENGINEER,
)

# ServiceTerritory.posture
POSTURE_PENDING = "PENDING"
POSTURE_MAPPING = "MAPPING"
POSTURE_VALIDATING = "VALIDATING"
POSTURE_ACTIVE = "ACTIVE"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_SUSPENDED = "SUSPENDED"

# Vehicle.status
VEHICLE_DRAFT = "DRAFT"
VEHICLE_IN_SERVICE = "IN_SERVICE"
VEHICLE_AT_DEPOT = "AT_DEPOT"
VEHICLE_ROADSIDE = "ROADSIDE"
VEHICLE_SUSPENDED = "SUSPENDED"

# Vehicle.service_status
SERVICE_UNAVAILABLE = "UNAVAILABLE"
SERVICE_AVAILABLE = "AVAILABLE"
SERVICE_DISPATCHED = "DISPATCHED"
SERVICE_ON_TRIP = "ON_TRIP"

# DepotSite.posture
DEPOT_OPEN = "OPEN"
DEPOT_CONGESTED = "CONGESTED"
DEPOT_LOCKDOWN = "LOCKDOWN"

# BaySlot.status
SLOT_RESERVED = "RESERVED"
SLOT_ACTIVE = "ACTIVE"
SLOT_COMPLETED = "COMPLETED"
SLOT_RELEASED = "RELEASED"

# DepotCycle.status
CYCLE_STAGED = "STAGED"
CYCLE_IN_PROGRESS = "IN_PROGRESS"
CYCLE_COMPLETED = "COMPLETED"
CYCLE_ABORTED = "ABORTED"

# Service kinds / bay service types
KIND_CHARGE = "CHARGE"
KIND_CLEAN = "CLEAN"
KIND_CALIBRATION = "CALIBRATION"
KIND_SOFTWARE = "SOFTWARE"

# RideRequest.status
RIDE_REQUESTED = "REQUESTED"
RIDE_MATCHED = "MATCHED"
RIDE_PICKED_UP = "PICKED_UP"
RIDE_COMPLETED = "COMPLETED"
RIDE_CANCELLED_NO_SHOW = "CANCELLED_NO_SHOW"
RIDE_CANCELLED = "CANCELLED"
RIDE_FAILED = "FAILED"

# AssistanceSession.status
SESSION_ESCALATED = "ESCALATED"
SESSION_ACKNOWLEDGED = "ACKNOWLEDGED"
SESSION_RESOLVED = "RESOLVED"
SESSION_UNRESOLVED = "UNRESOLVED"

# IncidentReport.status
INCIDENT_FILED = "FILED"
INCIDENT_UNDER_REVIEW = "UNDER_REVIEW"
INCIDENT_CLOSED = "CLOSED"
INCIDENT_VOIDED = "VOIDED"

# RoadsideCase.status
CASE_OPEN = "OPEN"
CASE_TEAM_ASSIGNED = "TEAM_ASSIGNED"
CASE_RESPONSE_DISPATCHED = "RESPONSE_DISPATCHED"
CASE_CLEARED = "CLEARED"
CASE_CANCELLED = "CANCELLED"

# RoadsideTeam.status
TEAM_AVAILABLE = "AVAILABLE"
TEAM_ON_CASE = "ON_CASE"
TEAM_OFF_SHIFT = "OFF_SHIFT"

# ServiceAreaRule.status
RULE_DRAFT = "DRAFT"
RULE_APPROVED = "APPROVED"
RULE_RETIRED = "RETIRED"

# ServiceAreaExpansionRequest.status
EXPANSION_SUBMITTED = "SUBMITTED"
EXPANSION_MAPPING_COMPLETE = "MAPPING_COMPLETE"
EXPANSION_VALIDATION_FAILED = "VALIDATION_FAILED"
EXPANSION_CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
EXPANSION_APPROVED = "APPROVED"
EXPANSION_REJECTED = "REJECTED"

# ExclusionZone.status
ZONE_SCHEDULED = "SCHEDULED"
ZONE_ACTIVE = "ACTIVE"
ZONE_EXPIRED = "EXPIRED"

# Window codes
WINDOW_MORNING_PEAK = "MORNING_PEAK"
WINDOW_MIDDAY = "MIDDAY"
WINDOW_EVENING_PEAK = "EVENING_PEAK"
WINDOW_OVERNIGHT = "OVERNIGHT"

# Route classes and curb access classes
ROUTE_FREEWAY = "FREEWAY"
ROUTE_ARTERIAL = "ARTERIAL"
ROUTE_RESIDENTIAL = "RESIDENTIAL"
ROUTE_ALLEY = "ALLEY"

CURB_SAFE = "SAFE"
CURB_NO_STOPPING = "NO_STOPPING"
CURB_LOADING_ONLY = "LOADING_ONLY"

SUB_SERVICE_STANDARD = "STANDARD"
SUB_SERVICE_ASSISTED = "ASSISTED"

# DeploymentWave / DepotCycle lifecycle status
WAVE_PLANNED = "PLANNED"
WAVE_ACTIVE = "ACTIVE"
WAVE_COMPLETED = "COMPLETED"
WAVE_ABORTED = "ABORTED"

# ─── Readiness doctrine (PRD 2.5) ─────────────────────────────────────────

MIN_BATTERY_PCT = 80
MIN_CLEANLINESS_SCORE = 70
DEFAULT_CLEANLINESS_SCORE = 100
DEFAULT_CALIB_VALID = False

# ─── Depot posture (PRD 2.6) ──────────────────────────────────────────────

CONGESTION_THRESHOLD_PCT = 80

# ─── Territory posture (PRD 2.7) ──────────────────────────────────────────

RESTRICTED_ZONE_COUNT = 3
SUSPENDED_ZONE_COUNT = 5
MAPPED_PCT_GATE = 95
VALIDATION_HOURS_GATE = 100

# ─── Wave allocation (PRD 3.3) ────────────────────────────────────────────

RESERVE_TARGET = 6


def reserve_floor(planned_vehicle_count):
    """6 divided by the wave budget, rounded up once per wave (PRD 3.3)."""
    return int(math.ceil(RESERVE_TARGET / float(planned_vehicle_count)))


def wave_allocation_cap(planned_vehicle_count, available_candidates):
    """min(budget, candidates - reserve_floor), floored at zero (PRD 3.3)."""
    return max(0, min(planned_vehicle_count, available_candidates - reserve_floor(planned_vehicle_count)))


# ─── Ride-credit arithmetic (PRD 2.10) ────────────────────────────────────

CREDIT_NUMERATOR = 5_000_000
FIXED_DENOMINATOR = 500
OPEN_MULTIPLIER = 10
RESTRICTED_MULTIPLIER = 5


def effective_demand(projected_rides, manual_only_rides):
    """max(0, projected_rides - manual_only_rides) (PRD 2.10)."""
    return max(0, projected_rides - manual_only_rides)


def credit_provision(effective, posture):
    """10 * demand, halved to 5 * demand when the territory is RESTRICTED."""
    multiplier = RESTRICTED_MULTIPLIER if posture == POSTURE_RESTRICTED else OPEN_MULTIPLIER
    return multiplier * effective


def credit_per_ride(effective, posture):
    """floor(5,000,000 / (provision + 500)) (PRD 2.10)."""
    provision = credit_provision(effective, posture)
    return CREDIT_NUMERATOR // (provision + FIXED_DENOMINATOR)


def total_credit_cents(effective, posture):
    """floor(5,000,000 * provision / (provision + 500)) (PRD 2.10)."""
    provision = credit_provision(effective, posture)
    return (CREDIT_NUMERATOR * provision) // (provision + FIXED_DENOMINATOR)


# ─── Incident retention (PRD 3.5) ─────────────────────────────────────────

CRASH_RETENTION_DAYS = 365
STANDARD_RETENTION_DAYS = 180
SECONDS_PER_DAY = 86_400
CRASH_RETENTION_SECONDS = CRASH_RETENTION_DAYS * SECONDS_PER_DAY   # 31,536,000
STANDARD_RETENTION_SECONDS = STANDARD_RETENTION_DAYS * SECONDS_PER_DAY  # 15,552,000


def retention_days(severity):
    """365 for MODERATE/SEVERE, 180 for MINOR (PRD 3.5)."""
    return CRASH_RETENTION_DAYS if severity in ("MODERATE", "SEVERE") else STANDARD_RETENTION_DAYS


def crash_evidence_retained(severity):
    """True exactly when severity is MODERATE or SEVERE (PRD 3.5)."""
    return severity in ("MODERATE", "SEVERE")


# ─── Operational cadence ──────────────────────────────────────────────────

CYCLE_SLA_OPS_RUNS = 2
ROADSIDE_SLA_OPS_RUNS = 4
MAX_DISPATCHED_PER_TEAM = 2
ACK_TIMEOUT_OPS_RUNS = 3
MAX_SESSION_ATTEMPTS = 3

# ─── Logical clock ────────────────────────────────────────────────────────

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
BASE_INSTANT = "2026-06-01T00:00:00Z"