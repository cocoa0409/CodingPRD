"""Authentication and authorization helpers (PRD section 2.1 / 2.9)."""
from flask import request

import db as dbmod
from errors import ApiError

ROLES = {
    "PlatformAdmin",
    "AccountManager",
    "LabProcurement",
    "ServiceDispatcher",
    "FieldEngineer",
    "SupplyOps",
}


def authenticate(allowed_roles):
    """Validate identity headers, entity-backed identity, and endpoint role list.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) then
    ERR_FORBIDDEN (403) per the validation priority order.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if role == "LabProcurement" and uid not in dbmod.store.accounts:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID does not identify an existing Account",
        )
    if role == "FieldEngineer" and uid not in dbmod.store.engineers:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID does not identify an existing Engineer",
        )
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted on this endpoint")
    return uid, role


def forbid(message="Access to another party's resource is forbidden"):
    raise ApiError("ERR_FORBIDDEN", 403, message)


def get_body():
    """Return the JSON request body as a dict; {} when absent, 400 when not an object."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body
