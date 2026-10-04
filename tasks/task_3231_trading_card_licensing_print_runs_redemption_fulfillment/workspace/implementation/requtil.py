"""Request body parsing helpers.

PRD 3.9: a malformed request — an unparseable body, a value of the wrong JSON
type, or a required input field missing entirely — is refused with
ERR_INVALID_REQUEST, settled before business rules are evaluated.
"""

from flask import request

from constants import parse_dt
from errors import ApiError, ERR_INVALID_REQUEST


def body():
    """Return the request body as a dict.  An absent body is an empty dict;
    an unparseable or non-object body is ERR_INVALID_REQUEST."""
    raw = request.get_json(silent=True)
    if raw is None:
        # Tolerate a completely empty body for action endpoints that take none.
        if request.data:
            raise ApiError(ERR_INVALID_REQUEST, "Request body is not valid JSON")
        return {}
    if not isinstance(raw, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return raw


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Required field %s is missing" % field)
    return data[field]


def required_str(data, field):
    value = required(data, field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return value


def required_int(data, field):
    value = required(data, field)
    return as_int(value, field)


def required_bool(data, field):
    value = required(data, field)
    return as_bool(value, field)


def required_dt(data, field):
    value = required(data, field)
    return as_dt(value, field)


def required_enum(data, field, allowed):
    value = required_str(data, field)
    if value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field %s must be one of: %s" % (field, ", ".join(allowed)),
        )
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return value


def as_str(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return value


def as_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an ISO-8601 string" % field)
    parsed = parse_dt(value)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s is not a valid ISO-8601 instant" % field)
    return parsed


def as_number(value, field):
    """A JSON number (int or float) accepted for demand_multiplier."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return value


def optional_str(data, field, default=None):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return value


def optional_int(data, field, default=None):
    value = data.get(field)
    if value is None:
        return default
    return as_int(value, field)


def optional_enum(data, field, allowed, default=None):
    value = data.get(field)
    if value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field %s must be one of: %s" % (field, ", ".join(allowed)),
        )
    return value


def optional_dt(data, field, default=None):
    value = data.get(field)
    if value is None:
        return default
    return as_dt(value, field)


def filter_value(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return value