"""Auth (PRD 2.1) and request-shape validation helpers (PRD 2.8 rows 1-3)."""
from flask import request

import clock
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_REQUEST,
)

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_CAPACITY_PLANNER = "CapacityPlanner"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_DEVICE_MAKER = "DeviceMaker"

DECLARED_ROLES = frozenset(
    [
        ROLE_PLATFORM_ADMIN,
        ROLE_PROGRAM_MANAGER,
        ROLE_CAPACITY_PLANNER,
        ROLE_FINANCE_CONTROLLER,
        ROLE_LEGAL_COUNSEL,
        ROLE_DEVICE_MAKER,
    ]
)

# GET endpoints accept any of the six declared roles.
ALL_ROLES = DECLARED_ROLES


def authenticate(allowed_roles):
    """Priority 1 (authentication) then 2 (authorization). Returns X-User-ID."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or unrecognized X-User-Role / X-User-ID headers",
        )
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN_ROLE, "Role not permitted on this endpoint")
    return user_id


def _bad(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def get_body():
    """Return the JSON object body; a missing body is treated as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        _bad("Missing required field: " + name)
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        _bad("Field " + name + " must be a string")
    return value


def as_int(value, name):
    if isinstance(value, bool):
        _bad("Field " + name + " must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    _bad("Field " + name + " must be an integer")


def as_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field " + name + " must be a number")
    return float(value)


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad("Field " + name + " must be one of " + ", ".join(sorted(allowed)))
    return value


def as_datetime(value, name):
    if not isinstance(value, str):
        _bad("Field " + name + " must be an ISO 8601 datetime string")
    try:
        return clock.parse_iso(value)
    except ValueError:
        _bad("Field " + name + " must be an ISO 8601 datetime string")


def pagination_args():
    """limit (default 10, min 1, max 100) and offset (default 0), clamped."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
