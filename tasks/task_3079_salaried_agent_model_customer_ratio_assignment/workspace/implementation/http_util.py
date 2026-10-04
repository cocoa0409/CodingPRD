"""Request body / query parsing, header authentication and role entitlement."""

from flask import request

from errors import ApiError
from constants import ROLES, PAGINATION_DEFAULT_LIMIT, \
    PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT, PAGINATION_DEFAULT_OFFSET
from db import db


# ---------------------------------------------------------------------------
# Body / query access
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def q(name, default=None):
    v = request.args.get(name)
    return default if v is None or v == "" else v


def require(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required input '%s'." % field)
    return data[field]


def require_str(data, field):
    value = require(data, field)
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a non-empty string." % field)
    return value


def require_int(data, field):
    value = require(data, field)
    return as_int(value, field)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                raise ApiError("ERR_INVALID_REQUEST", "'%s' must be an integer." % field)
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be an integer." % field)
    return value


def as_number(value, field):
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a number." % field)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a number." % field)
    raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a number." % field)


def optional_int(data, field, default=0):
    if field not in data or data[field] is None:
        return default
    return as_int(data[field], field)


def enum(data, field, allowed, required=True):
    if field not in data or data[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required input '%s'." % field)
        return None
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "'%s' is not a declared value." % field)
    return value


def score_in_range(value, field, lo=1, hi=5):
    n = as_int(value, field)
    if n < lo or n > hi:
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be within %d..%d." % (field, lo, hi))
    return n


def pagination():
    limit_raw = q("limit")
    offset_raw = q("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST",
                           "limit must be within %d..%d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


# ---------------------------------------------------------------------------
# Identity and entitlement
# ---------------------------------------------------------------------------
def identity():
    """Returns (role, user_id). Raises ERR_UNAUTHENTICATED when unusable."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None:
        raise ApiError("ERR_UNAUTHENTICATED", http_status=401)
    role = role.strip()
    user_id = user_id.strip()
    if role == "" or user_id == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", http_status=401)
    return role, user_id


def require_role(*allowed):
    """Auth first (401), then entitlement (403)."""
    role, user_id = identity()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", http_status=403)
    return role, user_id


def optional_identity_require_role(*allowed):
    """Bootstrap endpoints (region creation and single-region read) are exempt
    from the authentication check: with no identity presented they are simply
    allowed. When identity IS presented it is validated as usual."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None:
        return None, None
    role = role.strip()
    user_id = user_id.strip()
    if role == "" or user_id == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", http_status=401)
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", http_status=403)
    return role, user_id


def acting_agent_id(user_id):
    """For entity-backed roles the X-User-ID must resolve to an existing Agent."""
    if user_id not in db.agents:
        raise ApiError("ERR_FORBIDDEN", http_status=403)
    return user_id
