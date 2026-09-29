"""Schema validation (precedence check 4 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import fail
from util import parse_dt

_MISSING = object()


def json_body(required=True):
    """Parse the request body. Non-object payloads are schema failures."""
    data = request.get_json(silent=True, force=True)
    if data is None:
        if required:
            fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def present(body, key):
    return key in body and body[key] is not None


def _require_present(body, key):
    if key not in body or body[key] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required and may not be null." % key)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, key, min_len=1, max_len=None, non_blank=True):
    _require_present(body, key)
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if non_blank and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' may not be blank." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is longer than %d characters." % (key, max_len))
    return value


def req_int(body, key, minimum=None, maximum=None):
    _require_present(body, key)
    value = body[key]
    if not is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (key, maximum))
    return value


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not present(body, key):
        return default
    return req_int(body, key, minimum, maximum)


def opt_str(body, key, min_len=1, max_len=None, default=None, non_blank=True):
    if not present(body, key):
        return default
    return req_str(body, key, min_len, max_len, non_blank)


def req_bool(body, key):
    _require_present(body, key)
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def req_enum(body, key, allowed):
    _require_present(body, key)
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_dt(body, key):
    _require_present(body, key)
    value = body[key]
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def req_enum_array(body, key, allowed, unique=True):
    _require_present(body, key)
    value = body[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' entries must be one of %s." % (key, ", ".join(allowed)))
        if unique and item in seen:
            fail("ERR_INVALID_REQUEST", "Field '%s' may not contain duplicates." % key)
        seen.append(item)
    return seen


# --- query-string helpers ----------------------------------------------------

def q_pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _q_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _q_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' may not be negative.")
    return limit, offset


def _q_int(name, raw):
    text = raw.strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def q_str(name):
    return request.args.get(name)
