"""Authentication, RBAC, request-body parsing and pagination."""

from flask import request

from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    fail,
)

ROLES = ("NetworkAdmin", "MemberFoodBank", "NetworkAuditor")

MEMBER_ACTOR = "MemberFoodBank"


def actor():
    """Extract and validate the identity headers (validation rank 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED,
             "X-User-ID and X-User-Role are required and X-User-Role must name "
             "a declared role")
    return user_id, role


def require_roles(*allowed):
    """Auth plus the endpoint's role list (validation ranks 1 and 4)."""
    user_id, role = actor()
    if role not in allowed:
        fail(ERR_FORBIDDEN, "role %s is not authorized for this operation" % role)
    return user_id, role


def require_owning_member(user_id, role, owner_member_id):
    """MemberFoodBank callers may only act as themselves."""
    if role == MEMBER_ACTOR and owner_member_id is not None and owner_member_id != user_id:
        fail(ERR_FORBIDDEN, "a member food bank may only act on its own resources")


# --------------------------------------------------------------------------
# request body
# --------------------------------------------------------------------------

def json_body():
    """Parse a JSON object body (validation rank 2)."""
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "the request body must be a JSON object")
    return data


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key):
    if not _present(data, key) or not isinstance(data[key], str) or not data[key].strip():
        fail(ERR_INVALID_REQUEST, "%s is required and must be a non-empty string" % key)
    return data[key]


def req_int(data, key):
    if not _present(data, key) or isinstance(data[key], bool) or not isinstance(data[key], int):
        fail(ERR_INVALID_REQUEST, "%s is required and must be an integer" % key)
    return data[key]


def req_bool(data, key):
    if not _present(data, key) or not isinstance(data[key], bool):
        fail(ERR_INVALID_REQUEST, "%s is required and must be a boolean" % key)
    return data[key]


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        fail(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def opt_str(data, key, default=None):
    if not _present(data, key):
        return default
    if not isinstance(data[key], str):
        fail(ERR_INVALID_REQUEST, "%s must be a string" % key)
    return data[key]


def opt_int(data, key, default=None):
    if not _present(data, key):
        return default
    if isinstance(data[key], bool) or not isinstance(data[key], int):
        fail(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return data[key]


def opt_number(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(ERR_INVALID_REQUEST, "%s must be a number" % key)
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def opt_raw(data, key, default=None):
    """A free-form optional value (variant selectors such as activity_basis)."""
    if not _present(data, key):
        return default
    return data[key]


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail(ERR_INVALID_REQUEST, "%s must be an integer" % name)


def paginate(rows):
    """Apply the scaffold's limit/offset contract to an ordered row list."""
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1 or limit > 100:
        fail(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        fail(ERR_INVALID_REQUEST, "offset must be zero or greater")
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
