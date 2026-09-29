"""Request-schema helpers. Every violation here is ERR_INVALID_REQUEST (PRD 2.12 priority 3)."""
from flask import request

from errors import fail
from util import parse_date, parse_instant

MISSING = object()


def get_body():
    """Parse the JSON body. Absent body is an empty object; a non-object body is a schema error."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, mn=1, mx=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return _string(body[name], name, mn, mx)


def opt_string(body, name, mn=1, mx=None, default=None):
    if not _present(body, name):
        return default
    return _string(body[name], name, mn, mx)


def _string(value, name, mn, mx):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if mn is not None and len(value) < mn:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (name, mn))
    if mx is not None and len(value) > mx:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (name, mx))
    return value


def req_enum(body, name, allowed):
    value = req_string(body, name, 1, None)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, mn=None, mx=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return _int(body[name], name, mn, mx)


def opt_int(body, name, mn=None, mx=None, default=None):
    if not _present(body, name):
        return default
    return _int(body[name], name, mn, mx)


def _int(value, name, mn, mx):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if mn is not None and value < mn:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, mn))
    if mx is not None and value > mx:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, mx))
    return value


def req_number(body, name, mn=None, mx=None):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return _number(body[name], name, mn, mx)


def opt_number(body, name, mn=None, mx=None, default=None):
    if not _present(body, name):
        return default
    return _number(body[name], name, mn, mx)


def _number(value, name, mn, mx):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if mn is not None and value < mn:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, mn))
    if mx is not None and value > mx:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, mx))
    return value


def req_bool(body, name):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    if not isinstance(body[name], bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return body[name]


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_date(body, name):
    value = req_string(body, name, 1, None)
    if parse_date(value) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 calendar date (YYYY-MM-DD)" % name)
    return value


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return req_date(body, name)


def req_instant(body, name):
    value = req_string(body, name, 1, None)
    if parse_instant(value) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % name)
    return value


def opt_instant(body, name, default=None):
    if not _present(body, name):
        return default
    return req_instant(body, name)


def req_value_map(body, name, mn=1, mx=40):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = body[name]
    if not isinstance(value, dict):
        fail("ERR_INVALID_REQUEST", "%s must be an object" % name)
    if len(value) < mn or len(value) > mx:
        fail("ERR_INVALID_REQUEST", "%s must have between %d and %d entries" % (name, mn, mx))
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            fail("ERR_INVALID_REQUEST", "%s keys and values must be strings" % name)
    return dict(value)


def req_str_array(body, name, mn=1, mx=40, item_mn=1, item_mx=32):
    if not _present(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = body[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
    if len(value) < mn or len(value) > mx:
        fail("ERR_INVALID_REQUEST", "%s must have between %d and %d items" % (name, mn, mx))
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "%s items must be strings" % name)
        if len(item) < item_mn or len(item) > item_mx:
            fail("ERR_INVALID_REQUEST",
                 "%s items must be %d-%d characters" % (name, item_mn, item_mx))
    return list(value)
