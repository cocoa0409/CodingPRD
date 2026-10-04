from flask import request

from errors import ApiError
from util import ALL_ROLES


def current_user():
    """Extract X-User-ID / X-User-Role. Raises ERR_UNAUTHENTICATED (401) on
    missing, blank, or undeclared role — priority 1 for every endpoint."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-ID header is required")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role header is required")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role names an undeclared role")
    return str(user_id), role


def require_roles(role, allowed):
    """Priority 2: role must be permitted for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role %s is not permitted for this endpoint" % role)


def require_fields(body, fields):
    """Priority 13 money/range family — missing required field is ERR_INVALID_REQUEST."""
    for field in fields:
        if field not in body or body[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", 422, "Missing required field: %s" % field)


def require_int(body, field, minimum=None, gt_zero=False):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be an integer" % field)
    if gt_zero and value <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be greater than zero" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be >= %d" % (field, minimum))
    return value


def require_enum(body, field, allowed):
    value = body.get(field)
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be one of %s" % (field, allowed))
    return value


def require_str(body, field):
    value = body.get(field)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 422, "%s must be a string" % field)
    return value
