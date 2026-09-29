"""Authentication, role authorization and Driver ownership scope (PRD 2.1, 2.9)."""
from flask import request

import constants
from errors import ApiError


def authenticate():
    """Rung 1: both headers present and the role is one of the five declared names."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in constants.ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(*allowed_roles):
    """Rungs 1 and 2: authenticate, then check the role against the endpoint list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def check_scope(user_id, role, driver_reference):
    """Rung 3: a Driver may only address its own rows."""
    if role != constants.ROLE_DRIVER:
        return
    if driver_reference is None:
        return
    if driver_reference != user_id:
        raise ApiError("ERR_DRIVER_SCOPE_VIOLATION")


def is_driver(role):
    return role == constants.ROLE_DRIVER
