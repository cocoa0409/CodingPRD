"""Auth: header extraction and role checking per PRD 2.1 and SCAFFOLD roles."""

from flask import request

import errors

ROLES = {
    "FleetAdmin",
    "FlowController",
    "StationOperator",
    "FloorSupervisor",
    "SafetyOfficer",
    "MaintenanceTech",
    "ReleaseEngineer",
}


def actor():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED on any problem."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(allowed):
    """Raise ERR_FORBIDDEN if acting role not in allowed set."""
    user_id, role = actor()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role
