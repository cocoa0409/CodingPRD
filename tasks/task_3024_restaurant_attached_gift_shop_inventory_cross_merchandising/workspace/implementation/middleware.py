"""Authentication, authorization and request-body parsing.

Auth — SCAFFOLD validations priority 1 and 2 / PRD 2.1:
  * `X-User-ID` and `X-User-Role` must both be present and the role must be one
    of the eight declared roles, otherwise ERR_UNAUTHENTICATED (401).
  * The role must be permitted for the operation, otherwise ERR_UNAUTHORIZED (403).
"""

from flask import request

from errors import ApiError

DECLARED_ROLES = {
    "PlatformAdmin",
    "AssortmentPlanner",
    "BoutiqueManager",
    "RetailLead",
    "RetailCashier",
    "Cashier",
    "Server",
    "Anonymous",
}

# Roles whose X-User-ID names a persisted StaffShift (PRD 2.1).
ENTITY_BACKED_ROLES = {"Cashier", "Server"}


def context():
    """Extract and validate the caller identity (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in DECLARED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return {"user_id": user_id, "role": role}


def require_role(ctx, allowed):
    """Priority 2: is the declared role permitted for this operation?"""
    if ctx["role"] not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return ctx


def body():
    """Parse the JSON request body, defaulting to an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data()
        if not raw:
            return {}
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


# ---------------------------------------------------------------------------
# Field extraction with type/bound enforcement
# ---------------------------------------------------------------------------

def required(data, field, kind=str):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Required field %s is missing." % field)
    return coerce(data[field], field, kind)


def optional(data, field, default=None, kind=str):
    if field not in data or data[field] is None:
        return default
    return coerce(data[field], field, kind)


def coerce(value, field, kind):
    try:
        if kind is str:
            if isinstance(value, (dict, list)):
                raise ValueError
            return value if isinstance(value, str) else str(value)
        if kind is int:
            if isinstance(value, bool):
                raise ValueError
            return int(value)
        if kind is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in ("true", "1"):
                    return True
                if value.lower() in ("false", "0"):
                    return False
            raise ValueError
        if kind is list:
            if not isinstance(value, list):
                raise ValueError
            return value
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is not a valid %s." % (field, kind.__name__))
    return value


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw.lower() in ("true", "1")


def matches(record, filters):
    """Apply a mapping of field -> expected value as an AND filter."""
    for field, expected in filters.items():
        if expected is None:
            continue
        if record.get(field) != expected:
            return False
    return True