"""Payload-shape validation helpers (PRD section 2.9 step 5)."""

from flask import request

import store
from errors import fail

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def present(payload, name):
    return name in payload and payload[name] is not None


def req_string(payload, name, min_len=1, max_len=None):
    if not present(payload, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s is too short" % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long" % name)
    return value


def opt_string(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return value


def req_enum(payload, name, allowed):
    value = req_string(payload, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = payload[name]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return req_int(payload, name, minimum, maximum)


def req_number(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return value


def opt_number(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return req_number(payload, name, minimum, maximum)


def req_bool(payload, name):
    if not present(payload, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return value


def opt_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    return req_bool(payload, name)


def req_date(payload, name):
    value = req_string(payload, name)
    parsed = store.parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO calendar date" % name)
    return parsed


def opt_date(payload, name, default=None):
    if not present(payload, name):
        return default
    return req_date(payload, name)


def req_id(payload, name):
    return req_string(payload, name)


# ---------------------------------------------------------------------------
# pagination + query helpers
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def query(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_enum(name, allowed):
    value = query(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def query_date(name):
    value = query(name)
    if value is None:
        return None
    parsed = store.parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO calendar date" % name)
    return parsed


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
