"""Request shape helpers.

PRD section 2.8 step 6 -- request shape is checked with ERR_INVALID_REQUEST
before any enum membership test (step 7), so these helpers only ever validate
presence and JSON type.  Enum membership lives in ``check_enum``.

Fields the specification marks as system-maintained or computed are simply not
read here, which is how "ignored when a client supplies them, never rejected"
is realised.
"""
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import fail

_MISSING = object()


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return payload


def present(b, key):
    return key in b and b[key] is not None


def s_str(b, key, required=True, allow_empty=False, default=None):
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return default
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must not be blank." % key)
    return value


def s_id(b, key, required=True):
    return s_str(b, key, required=required)


def s_int(b, key, required=True, minimum=None, maximum=None, default=None):
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (key, maximum))
    return value


def s_num(b, key, required=True, minimum=None, default=None):
    """A JSON number, returned as Decimal."""
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    return dec


def s_bool(b, key, required=True, default=None):
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return default
    value = b[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def s_dt(b, key, required=True, default=None):
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % key)
        return default
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant string." % key)
    parsed = db.parse_instant(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant string." % key)
    return parsed


def check_enum(key, value, allowed):
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_ENUM_VALUE", "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


# --------------------------------------------------------------------------
# query string filters
# --------------------------------------------------------------------------


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, allowed):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_ENUM_VALUE", "%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def q_bool(name):
    raw = q_str(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be true or false." % name)


def q_int(name, minimum=None):
    raw = q_str(name)
    if raw is None:
        return None
    text = raw.strip()
    if not text.lstrip("+-").isdigit():
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s is out of bounds." % name)
    return value


def q_dt(name):
    raw = q_str(name)
    if raw is None:
        return None
    parsed = db.parse_instant(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 instant string." % name)
    return parsed
