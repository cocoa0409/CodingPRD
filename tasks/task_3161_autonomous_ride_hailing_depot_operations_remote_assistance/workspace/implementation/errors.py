"""Error catalog for the fleet interface.

The identifiers and HTTP status codes are taken verbatim from PRD section 5 /
SCAFFOLD section 1.6.  Nothing in this module is stateful.
"""


class ApiError(Exception):
    """A domain failure carrying the PRD's error_id and HTTP status."""

    def __init__(self, error_id: str, http_status: int, message: str = ""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ─── identifiers ──────────────────────────────────────────────────────────

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ROUTE_NOT_ALLOWED = "ERR_ROUTE_NOT_ALLOWED"
ERR_EXCLUSION_ZONE_ACTIVE = "ERR_EXCLUSION_ZONE_ACTIVE"
ERR_WEATHER_SUSPENDED = "ERR_WEATHER_SUSPENDED"
ERR_CURB_ACCESS_DENIED = "ERR_CURB_ACCESS_DENIED"
ERR_LOCATION_INVALID = "ERR_LOCATION_INVALID"
ERR_VEHICLE_IN_CYCLE = "ERR_VEHICLE_IN_CYCLE"
ERR_VEHICLE_NOT_SERVICE_READY = "ERR_VEHICLE_NOT_SERVICE_READY"
ERR_VEHICLE_ROADSIDE_BLOCKED = "ERR_VEHICLE_ROADSIDE_BLOCKED"
ERR_VEHICLE_HAS_ACTIVE_CYCLE = "ERR_VEHICLE_HAS_ACTIVE_CYCLE"
ERR_BAY_SLOT_CONFLICT = "ERR_BAY_SLOT_CONFLICT"
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
ERR_POSTURE_LOCKDOWN = "ERR_POSTURE_LOCKDOWN"
ERR_TERRITORY_NOT_ACTIVE = "ERR_TERRITORY_NOT_ACTIVE"
ERR_ZONE_BLOCKED_WAVE = "ERR_ZONE_BLOCKED_WAVE"
ERR_NO_VEHICLE_AVAILABLE = "ERR_NO_VEHICLE_AVAILABLE"
ERR_NO_TEAM_AVAILABLE = "ERR_NO_TEAM_AVAILABLE"
ERR_TEAM_CAPACITY_EXCEEDED = "ERR_TEAM_CAPACITY_EXCEEDED"
ERR_RESPONSE_SLA_BREACHED = "ERR_RESPONSE_SLA_BREACHED"
ERR_CALIBRATION_SIGNOFF_REQUIRED = "ERR_CALIBRATION_SIGNOFF_REQUIRED"
ERR_MAX_ATTEMPTS_NOT_REACHED = "ERR_MAX_ATTEMPTS_NOT_REACHED"
ERR_SESSION_TERMINAL = "ERR_SESSION_TERMINAL"
ERR_CROSS_TERRITORY = "ERR_CROSS_TERRITORY"


# ─── HTTP status map (PRD section 5) ──────────────────────────────────────

HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_DUPLICATE_RESOURCE: 409,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_ROUTE_NOT_ALLOWED: 422,
    ERR_EXCLUSION_ZONE_ACTIVE: 422,
    ERR_WEATHER_SUSPENDED: 422,
    ERR_CURB_ACCESS_DENIED: 422,
    ERR_LOCATION_INVALID: 422,
    ERR_VEHICLE_IN_CYCLE: 409,
    ERR_VEHICLE_NOT_SERVICE_READY: 409,
    ERR_VEHICLE_ROADSIDE_BLOCKED: 409,
    ERR_VEHICLE_HAS_ACTIVE_CYCLE: 409,
    ERR_BAY_SLOT_CONFLICT: 409,
    ERR_CAPACITY_EXCEEDED: 409,
    ERR_POSTURE_LOCKDOWN: 409,
    ERR_TERRITORY_NOT_ACTIVE: 409,
    ERR_ZONE_BLOCKED_WAVE: 409,
    ERR_NO_VEHICLE_AVAILABLE: 409,
    ERR_NO_TEAM_AVAILABLE: 409,
    ERR_TEAM_CAPACITY_EXCEEDED: 409,
    ERR_RESPONSE_SLA_BREACHED: 409,
    ERR_CALIBRATION_SIGNOFF_REQUIRED: 400,
    ERR_MAX_ATTEMPTS_NOT_REACHED: 409,
    ERR_SESSION_TERMINAL: 409,
    ERR_CROSS_TERRITORY: 409,
}

MESSAGES = {
    ERR_UNAUTHENTICATED: "Missing or malformed X-User-Role / X-User-ID headers.",
    ERR_UNAUTHORIZED: "Calling role is not permitted for this operation.",
    ERR_NOT_FOUND: "Path resource does not exist.",
    ERR_INVALID_REQUEST: "Malformed body, missing required field, or wrong field type.",
    ERR_DUPLICATE_RESOURCE: "Unique key collision.",
    ERR_STALE_VERSION: "expected_*_version does not match the entity's current version.",
    ERR_INVALID_STATE: "Requested transition is not valid from the resource's current state.",
    ERR_ROUTE_NOT_ALLOWED: "Route class is outside the approved operational design domain.",
    ERR_EXCLUSION_ZONE_ACTIVE: "An ACTIVE ExclusionZone covers the requested route class.",
    ERR_WEATHER_SUSPENDED: "Weather tier is 3 or higher for a peak wave window.",
    ERR_CURB_ACCESS_DENIED: "Curb access class is not permitted for the ride's sub_service_type.",
    ERR_LOCATION_INVALID: "Pickup or dropoff location is no longer valid.",
    ERR_VEHICLE_IN_CYCLE: "Vehicle already has a DepotCycle in STAGED or IN_PROGRESS.",
    ERR_VEHICLE_NOT_SERVICE_READY: "Vehicle fails one or more readiness predicates.",
    ERR_VEHICLE_ROADSIDE_BLOCKED: "Vehicle is blocked by a RoadsideCase in RESPONSE_DISPATCHED.",
    ERR_VEHICLE_HAS_ACTIVE_CYCLE: "Vehicle has a DepotCycle IN_PROGRESS; it cannot be suspended.",
    ERR_BAY_SLOT_CONFLICT: "Requested bay window intersects a RESERVED or ACTIVE slot on the same bay.",
    ERR_CAPACITY_EXCEEDED: "Depot bay pool or wave budget would be exceeded.",
    ERR_POSTURE_LOCKDOWN: "Depot is in LOCKDOWN; cycle start is blocked.",
    ERR_TERRITORY_NOT_ACTIVE: "Territory is not ACTIVE.",
    ERR_ZONE_BLOCKED_WAVE: "Territory has one or more ACTIVE exclusion zones.",
    ERR_NO_VEHICLE_AVAILABLE: "The selector found no candidate vehicle in the territory.",
    ERR_NO_TEAM_AVAILABLE: "The roadside selector found no eligible team.",
    ERR_TEAM_CAPACITY_EXCEEDED: "The selected RoadsideTeam already holds two dispatched cases.",
    ERR_RESPONSE_SLA_BREACHED: "RoadsideCase has been OPEN for the whole response SLA allowance.",
    ERR_CALIBRATION_SIGNOFF_REQUIRED: "CALIBRATION completion requires signed_off == true.",
    ERR_MAX_ATTEMPTS_NOT_REACHED: "escalate-unresolved requires attempt_count >= 3.",
    ERR_SESSION_TERMINAL: "No AssistanceSession for the ride is ESCALATED or ACKNOWLEDGED.",
    ERR_CROSS_TERRITORY: "Referenced resource belongs to a different territory than the path.",
}


def fail(error_id: str) -> "ApiError":
    """Build an ApiError from the catalog, using the catalogued HTTP status."""
    return ApiError(error_id, HTTP_STATUS[error_id], MESSAGES.get(error_id, error_id))