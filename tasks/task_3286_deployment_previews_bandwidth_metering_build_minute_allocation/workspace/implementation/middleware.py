"""Auth middleware: X-User-ID / X-User-Role, RBAC enforcement, pagination parsing."""

from functools import wraps
from flask import request, g
from errors import err

ROLES = [
    "PlatformAdmin",
    "TeamOwner",
    "TeamBillingManager",
    "Developer",
    "Viewer",
    "SystemWebhook",
]


def require_roles(*allowed):
    """Decorator: validate auth headers then role membership."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers present and role is a declared role")
            g.user_id = user_id
            g.user_role = role
            if allowed and role not in allowed:
                err("ERR_INSUFFICIENT_PERMISSIONS",
                    "Role not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def parse_pagination():
    """Parse limit/offset query params per pagination defaults."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def body():
    """JSON body or {} (empty body allowed for transition endpoints)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def require_fields(data, *fields):
    for f in fields:
        if f not in data or data[f] is None:
            err("ERR_INVALID_REQUEST", f"missing required field: {f}")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(data, field):
    v = data.get(field)
    if not is_int(v):
        err("ERR_INVALID_REQUEST", f"field {field} must be an integer")
    return v


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", f"field {field} must be a string")
    return v


def opt_enum(data, field, choices, default=None):
    v = data.get(field, default)
    if v is None:
        return None
    if v not in choices:
        err("ERR_INVALID_REQUEST", f"field {field} must be one of {choices}")
    return v
