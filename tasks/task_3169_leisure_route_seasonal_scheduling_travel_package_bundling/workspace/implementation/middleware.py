"""Auth middleware: X-User-ID / X-User-Role header checks per PRD §2.1."""

from flask import request

from errors import missing_user_context, insufficient_permissions

ROLES = {
    "NetworkPlanner",
    "OpsController",
    "CrewScheduler",
    "CustomerService",
    "FinanceAnalyst",
}

ROLE_ENDPOINTS = {
    "NetworkPlanner": {
        "POST /stations",
        "POST /routes",
        "POST /routes/{routeId}/activate",
        "POST /routes/{routeId}/suspend",
        "POST /routes/{routeId}/reactivate",
        "POST /routes/{routeId}/close",
        "POST /routes/{routeId}/season-windows",
        "POST /routes/{routeId}/season-windows/{windowId}/suspend",
        "POST /routes/{routeId}/season-windows/{windowId}/close",
        "POST /routes/{routeId}/publications",
        "POST /routes/{routeId}/publications/{publicationId}/retire",
        "POST /_clock/set_current_utc",
    },
    "OpsController": {
        "POST /aircraft",
        "POST /aircraft/{aircraftId}/retire",
        "POST /flight-instances/{flightInstanceId}/assign-aircraft",
        "POST /flight-instances/{flightInstanceId}/mark-operated",
        "POST /routes/{routeId}/disruptions",
        "POST /_clock/set_current_utc",
    },
    "CrewScheduler": {
        "POST /crew-bases",
        "POST /crew-bases/{crewBaseId}/members",
        "POST /flight-instances/{flightInstanceId}/crew-assignments",
        "DELETE /flight-instances/{flightInstanceId}/crew-assignments/{assignmentId}",
        "POST /_clock/set_current_utc",
    },
    "CustomerService": {
        "POST /bookings",
        "POST /bookings/{bookingId}/rebook",
        "POST /bookings/{bookingId}/cancel",
        "POST /bookings/{bookingId}/ancillaries",
        "POST /bookings/{bookingId}/ancillaries/{purchaseId}/void",
        "POST /_clock/set_current_utc",
    },
    "FinanceAnalyst": {
        "POST /supplier-offers",
        "POST /supplier-settlements",
        "POST /supplier-settlements/{settlementId}/finalize",
        "POST /_clock/set_current_utc",
    },
}


def get_auth_headers():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth():
    """Validate auth headers. Raise on missing/invalid."""
    user_id, role = get_auth_headers()
    if not user_id or not role:
        raise missing_user_context()
    if role not in ROLES:
        raise missing_user_context()
    return user_id, role


def require_role(*allowed_roles):
    """Validate auth headers + role membership. Raise on failure."""
    user_id, role = require_auth()
    if role not in allowed_roles:
        raise insufficient_permissions()
    return user_id, role


def require_any_authenticated():
    """For GET endpoints and clock — any of the five roles is fine."""
    return require_auth()


def normalize_endpoint_key(method, path_template):
    """Build a canonical endpoint key for RBAC lookups."""
    return f"{method} {path_template}"
