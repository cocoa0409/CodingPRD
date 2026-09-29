"""Request-shape validation (priority 4 -> ERR_INVALID_REQUEST)."""

from flask import request

from db import parse_instant
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; {} when no body was sent."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        _bad("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object")
    return parsed


def required(payload, name):
    if name not in payload or payload[name] is None:
        _bad("%s is required" % name)
    return payload[name]


def optional(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    return payload[name]


def as_string(value, name, min_len=None, max_len=None, upper=False,
              exact_len=None):
    if not isinstance(value, str):
        _bad("%s must be a string" % name)
    if exact_len is not None and len(value) != exact_len:
        _bad("%s must be exactly %d characters" % (name, exact_len))
    if min_len is not None and len(value) < min_len:
        _bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s must be at most %d characters" % (name, max_len))
    if upper and any(ch.islower() for ch in value):
        _bad("%s must be uppercase" % name)
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %d" % (name, maximum))
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        _bad("%s must be a boolean" % name)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def as_instant(value, name):
    """Returns (raw string echoed back verbatim, parsed aware datetime)."""
    if not isinstance(value, str):
        _bad("%s must be an ISO-8601 UTC instant" % name)
    parsed = parse_instant(value)
    if parsed is None:
        _bad("%s must be an ISO-8601 UTC instant" % name)
    return value, parsed


def as_str_array(value, name, min_items=None, max_items=None, allowed=None):
    if not isinstance(value, list):
        _bad("%s must be an array" % name)
    if min_items is not None and len(value) < min_items:
        _bad("%s must contain at least %d entries" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        _bad("%s must contain at most %d entries" % (name, max_items))
    for item in value:
        if not isinstance(item, str):
            _bad("%s entries must be strings" % name)
        if allowed is not None and item not in allowed:
            _bad("%s entries must be one of %s" % (name, ", ".join(allowed)))
    if len(set(value)) != len(value):
        _bad("%s must not contain duplicate entries" % name)
    return list(value)


def as_int_array(value, name, minimum=None, min_items=None, max_items=None):
    if not isinstance(value, list):
        _bad("%s must be an array" % name)
    if min_items is not None and len(value) < min_items:
        _bad("%s must contain at least %d entries" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        _bad("%s must contain at most %d entries" % (name, max_items))
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            _bad("%s entries must be integers" % name)
        if minimum is not None and item < minimum:
            _bad("%s entries must be at least %d" % (name, minimum))
    if len(set(value)) != len(value):
        _bad("%s must not contain duplicate entries" % name)
    return list(value)


def as_id(value, name):
    if not isinstance(value, str) or not value:
        _bad("%s must be a resource id" % name)
    return value
