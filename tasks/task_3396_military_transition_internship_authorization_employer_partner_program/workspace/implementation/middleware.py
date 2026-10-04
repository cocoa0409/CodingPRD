from functools import wraps

from flask import request

import constants
import db
from errors import fail
from util import parse_iso_date


def locked(fn):
    """Serialize request handling on the in-memory store."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with db.store.lock:
            return fn(*args, **kwargs)

    return wrapper


def auth_context():
    """Priority 1: X-User-ID and X-User-Role present; role is a declared name."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in constants.ROLES:
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 3: role permitted to call this endpoint."""
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "Role %s may not call this endpoint" % role)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object")
    return data


# ---- Priority 2 schema validators (request body only) ----

def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str):
        fail("ERR_VALIDATION", "%s is required and must be a string" % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], str):
        fail("ERR_VALIDATION", "%s must be a string" % field)
    return data[field]


def req_int(data, field, min_value=None):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_VALIDATION", "%s is required and must be an integer" % field)
    if min_value is not None and v < min_value:
        fail("ERR_VALIDATION", "%s must be >= %d" % (field, min_value))
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        fail("ERR_VALIDATION", "%s is required and must be a boolean" % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s" % (field, ", ".join(sorted(allowed))))
    return v


def req_list_str(data, field):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        fail("ERR_VALIDATION", "%s is required and must be an array of strings" % field)
    return v


def opt_list_str(data, field):
    if field not in data or data[field] is None:
        return []
    return req_list_str(data, field)


def req_date(data, field):
    v = data.get(field)
    if v is None:
        fail("ERR_VALIDATION", "%s is required" % field)
    d = parse_iso_date(v)
    if d is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 date" % field)
    return d


def opt_date(data, field):
    if field not in data or data[field] is None:
        return None
    return req_date(data, field)
