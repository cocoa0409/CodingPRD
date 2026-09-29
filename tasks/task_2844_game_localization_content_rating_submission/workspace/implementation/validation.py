"""Request-shape validation -- rung 3 of the rejection ladder (PRD SS2.5)."""
from flask import request

from db import parse_instant
from errors import ApiError

_MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def json_body(required=True):
    if not request.data:
        if required:
            bad("A JSON object body is required")
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        payload = None
        bad("Body is not valid JSON")
    if payload is None:
        if required:
            bad("A JSON object body is required")
        return {}
    if not isinstance(payload, dict):
        bad("Body must be a JSON object")
    return payload


def present(body, name):
    return name in body


def _raw(body, name):
    return body.get(name, _MISSING)


def req_str(body, name, min_len=1, max_len=None):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        bad("%s is required" % name)
    return _check_str(value, name, min_len, max_len)


def opt_str(body, name, min_len=1, max_len=None, default=None, nullable=True):
    value = _raw(body, name)
    if value is _MISSING:
        return default
    if value is None:
        if nullable:
            return None
        bad("%s may not be null" % name)
    return _check_str(value, name, min_len, max_len)


def _check_str(value, name, min_len, max_len):
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    return value


def req_id(body, name):
    return req_str(body, name, 1, None)


def opt_id(body, name, default=None):
    return opt_str(body, name, 1, None, default)


def req_enum(body, name, allowed):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        bad("%s is required" % name)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None, nullable=True):
    value = _raw(body, name)
    if value is _MISSING:
        return default
    if value is None:
        if nullable:
            return None
        bad("%s may not be null" % name)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def _check_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        bad("%s is required" % name)
    return _check_int(value, name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None, nullable=True):
    value = _raw(body, name)
    if value is _MISSING:
        return default
    if value is None:
        if nullable:
            return None
        bad("%s may not be null" % name)
    return _check_int(value, name, minimum, maximum)


def opt_bool(body, name, default=None):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def req_instant(body, name):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        bad("%s is required" % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO-8601 UTC instant" % name)
    return parsed


def opt_instant(body, name, default=None):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        return default
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO-8601 UTC instant" % name)
    return parsed


def req_enum_list(body, name, allowed, non_empty=True):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        bad("%s is required" % name)
    return _check_enum_list(value, name, allowed, non_empty)


def opt_enum_list(body, name, allowed, default=None, non_empty=False):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        return list(default) if default is not None else []
    return _check_enum_list(value, name, allowed, non_empty)


def _check_enum_list(value, name, allowed, non_empty):
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if non_empty and len(value) == 0:
        bad("%s must not be empty" % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or (allowed is not None and item not in allowed):
            bad("%s contains an unrecognised value" % name)
        if item in seen:
            bad("%s must not contain duplicates" % name)
        seen.add(item)
    return list(value)


def opt_id_list(body, name, default=None):
    value = _raw(body, name)
    if value is _MISSING or value is None:
        return list(default) if default is not None else []
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    seen = set()
    for item in value:
        if not isinstance(item, str) or not item:
            bad("%s must contain identifier strings" % name)
        if item in seen:
            bad("%s must not contain duplicates" % name)
        seen.add(item)
    return list(value)
