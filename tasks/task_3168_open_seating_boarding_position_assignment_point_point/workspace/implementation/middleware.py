"""Authentication and role-based access control middleware."""
from __future__ import annotations

from flask import request

from errors import err_forbidden, err_unauthenticated

ROLES = {"Passenger", "GateAgent", "OpsController"}


def current_user():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Validate auth + role membership. Returns (user_id, role)."""
    user_id, role = current_user()
    if role not in roles:
        raise err_forbidden("Role not permitted for endpoint")
    return user_id, role


def require_owner(user_id, resource_passenger_id):
    if user_id != resource_passenger_id:
        raise err_forbidden("Passenger may only act on own resources")
