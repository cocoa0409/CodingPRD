"""Input-shape validation (validations[priority=4] / PRD sections 2.4 and 9).

Existence is checked before shape, so routes call these helpers only after all
path identifiers have resolved.
"""

from errors import ApiError


def body():
    from flask import request

    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def query_int(name, default, minimum=None, maximum=None):
    from flask import request

    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s is above its maximum." % name)
    return value


def query_bool(name):
    from flask import request

    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter %s must be a boolean." % name)


def pagination():
    limit = query_int("limit", 10, minimum=1, maximum=100)
    offset = query_int("offset", 0, minimum=0)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# -- presence ---------------------------------------------------------------

def require(payload, *names):
    for name in names:
        if name not in payload or payload[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
    return payload


def require_present(payload, *names):
    """Presence only — null is allowed but the key must exist."""
    for name in names:
        if name not in payload:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
    return payload


# -- scalar coercion --------------------------------------------------------

def as_str(payload, name, required=False):
    value = payload.get(name)
    if value is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    return value


def as_nonempty_str(payload, name, required=False):
    value = as_str(payload, name, required)
    if value is None:
        return None
    if value.strip() == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be non-empty." % name)
    return value


def as_int(payload, name, required=False, minimum=None, maximum=None, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
        return default
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is below its minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is above its maximum." % name)
    return value


def as_bool(payload, name, required=False, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
        return default
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return value


def as_enum(payload, name, allowed, required=False, default=None):
    if name not in payload or payload.get(name) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
        return default
    value = payload.get(name)
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is not a declared enum member." % name)
    return value


def as_instant(payload, name, required=False):
    from db import parse_iso

    value = as_str(payload, name, required)
    if value is None:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 instant." % name)


def occ(payload, name):
    """The OCC field is a required member of the body (PRD 2.7)."""
    if name not in payload:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s is required." % name)
    value = payload.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    return value