"""Request-shape validation: precedence position 7, ERR_INVALID_REQUEST (400)."""
from flask import request

import constants as C
import logical_clock as clockmod
from errors import fail


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def opt_str(data, field, min_len=0, max_len=None, default=None):
    if not present(data, field):
        return default
    return req_str(data, field, min_len, max_len)


def req_int(data, field, low=None, high=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if low is not None and value < low:
        _bad(field, "must be at least %d" % low)
    if high is not None and value > high:
        _bad(field, "must be at most %d" % high)
    return value


def opt_int(data, field, low=None, high=None, default=None):
    if not present(data, field):
        return default
    return req_int(data, field, low, high)


def req_enum(data, field, domain):
    value = req_str(data, field, 1, None)
    if value not in domain:
        _bad(field, "must be one of %s" % ", ".join(domain))
    return value


def opt_enum(data, field, domain, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, domain)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default=False):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_number(data, field, low=None, high=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    value = float(value)
    if low is not None and value < low:
        _bad(field, "must be at least %s" % low)
    if high is not None and value > high:
        _bad(field, "must be at most %s" % high)
    return value


def opt_number(data, field, low=None, high=None, default=None):
    if not present(data, field):
        return default
    return req_number(data, field, low, high)


def req_instant(data, field):
    raw = req_str(data, field, 1, None)
    parsed = clockmod.parse_instant(raw)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return parsed


def opt_instant(data, field, default=None):
    if not present(data, field):
        return default
    return req_instant(data, field)


def req_minute_of_day(data, field):
    return req_int(data, field, 0, C.MINUTES_PER_DAY - 1)


def opt_enum_array(data, field, domain, default=None):
    if not present(data, field):
        return list(default or [])
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for element in value:
        if not isinstance(element, str) or element not in domain:
            _bad(field, "elements must be one of %s" % ", ".join(domain))
    return list(value)


def opt_str_array(data, field, default=None):
    if not present(data, field):
        return list(default or [])
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for element in value:
        if not isinstance(element, str) or not element.strip():
            _bad(field, "elements must be non-blank strings")
    return list(value)


def req_dict_array(data, field, min_items=1):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, list) or len(value) < min_items:
        _bad(field, "must be an array of at least %d objects" % min_items)
    for element in value:
        if not isinstance(element, dict):
            _bad(field, "elements must be objects")
    return value
