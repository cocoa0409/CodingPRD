"""Request-body / query-string validation helpers (rank 5 of PRD 2.8)."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from store import parse_ts

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def body_json():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=1, max_len=None):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None):
    if not _present(body, key):
        return default
    return req_str(body, key, min_len=min_len, max_len=max_len)


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = body[key]
    if not is_int(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return req_int(body, key, minimum=minimum, maximum=maximum)


def req_num(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = body[key]
    if not is_number(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    try:
        dvalue = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if minimum is not None and dvalue < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % key)
    if maximum is not None and dvalue > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % key)
    return dvalue


def opt_num(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return req_num(body, key, minimum=minimum, maximum=maximum)


def req_bool(body, key):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    return req_bool(body, key)


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a recognized value." % key)
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_ts(body, key):
    if not _present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    value = parse_ts(body[key])
    if value is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC instant." % key)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and may not be negative."""
    limit = PAGE_LIMIT_DEFAULT
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' may not be negative.")
    return limit, offset


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
