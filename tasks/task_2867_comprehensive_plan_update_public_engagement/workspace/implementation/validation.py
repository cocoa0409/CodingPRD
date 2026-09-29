"""Request-shape validation - rung 4 of the ladder (PRD 2.8).

Every violation in this module raises ERR_INVALID_REQUEST (422).
"""
from decimal import Decimal

from flask import request

from db import parse_instant
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body. A missing or empty body is an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body must be valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _get(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return _MISSING if default is _MISSING else default
    return data[name]


def get_str(data, name, min_len=1, max_len=None, required=True, default=None,
            non_blank=True, pattern=None):
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if non_blank and not value.strip():
        bad("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (name, max_len))
    if pattern is not None and not pattern.match(value):
        bad("Field '%s' is malformed." % name)
    return value


def get_int(data, name, minimum=None, maximum=None, required=True, default=None):
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def get_num(data, name, minimum=None, maximum=None, required=True, default=None,
            exclusive_min=False):
    """Return a Decimal for a JSON number field."""
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    number = Decimal(str(value))
    if minimum is not None:
        if exclusive_min:
            if number <= Decimal(str(minimum)):
                bad("Field '%s' must be greater than %s." % (name, minimum))
        elif number < Decimal(str(minimum)):
            bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return number


def get_raw_num(data, name, required=True, default=None):
    """A number kept exactly as supplied (no rounding, PRD 2.6)."""
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    return value


def get_bool(data, name, required=False, default=False):
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def get_enum(data, name, members, required=True, default=None):
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def get_instant(data, name, required=True, default=None):
    value = _get(data, name, required, default)
    if (name not in data or data[name] is None):
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def get_str_list(data, name, members, required=True, non_empty=True):
    value = _get(data, name, required, None)
    if (name not in data or data[name] is None):
        return None
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if non_empty and not value:
        bad("Field '%s' must not be empty." % name)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in members:
            bad("Field '%s' contains an unrecognised member." % name)
        if item not in seen:
            seen.append(item)
    return seen
