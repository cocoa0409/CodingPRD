"""Request-shape validation (PRD 2.7 band 3) and pagination parsing (PRD 2.3)."""
import uuid as _uuid

from flask import request

import clock
from constants import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT, PAGE_LIMIT, PAGE_OFFSET
from errors import ApiError

_MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data and request.data.strip():
            _bad("Request body is not valid JSON.")
        return {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def _present(payload, key):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def req_str(payload, key, allow_empty=False):
    value = _present(payload, key)
    if value is _MISSING:
        _bad("'%s' is required." % key)
    if not isinstance(value, str):
        _bad("'%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        _bad("'%s' must be non-empty." % key)
    return value


def opt_str(payload, key, default=None, allow_empty=False):
    value = _present(payload, key)
    if value is _MISSING:
        return default
    return req_str(payload, key, allow_empty=allow_empty)


def _check_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("'%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("'%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("'%s' must be at most %d." % (key, maximum))
    return value


def req_int(payload, key, minimum=None, maximum=None):
    value = _present(payload, key)
    if value is _MISSING:
        _bad("'%s' is required." % key)
    return _check_int(value, key, minimum, maximum)


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    value = _present(payload, key)
    if value is _MISSING:
        return default
    return _check_int(value, key, minimum, maximum)


def req_bool(payload, key):
    value = _present(payload, key)
    if value is _MISSING:
        _bad("'%s' is required." % key)
    if not isinstance(value, bool):
        _bad("'%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    value = _present(payload, key)
    if value is _MISSING:
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        _bad("'%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(payload, key, allowed, default=None):
    value = _present(payload, key)
    if value is _MISSING:
        return default
    return req_enum(payload, key, allowed)


def req_uuid(payload, key):
    value = req_str(payload, key)
    try:
        _uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        _bad("'%s' must be a well-formed UUID." % key)
    return value


def opt_uuid(payload, key, default=None):
    value = _present(payload, key)
    if value is _MISSING:
        return default
    return req_uuid(payload, key)


def req_instant(payload, key):
    value = req_str(payload, key)
    parsed = clock.parse_iso8601(value)
    if parsed is None:
        _bad("'%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def pagination():
    raw_limit = request.args.get(PAGE_LIMIT)
    raw_offset = request.args.get(PAGE_OFFSET)
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        limit = _query_int(PAGE_LIMIT, raw_limit)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            _bad("'%s' must be between %d and %d." % (PAGE_LIMIT, LIMIT_MIN, LIMIT_MAX))
    if raw_offset is not None:
        offset = _query_int(PAGE_OFFSET, raw_offset)
        if offset < 0:
            _bad("'%s' must not be negative." % PAGE_OFFSET)
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    if text == "":
        _bad("'%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        _bad("'%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return _query_int(name, raw)


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    _bad("'%s' must be true or false." % name)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        _bad("'%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
