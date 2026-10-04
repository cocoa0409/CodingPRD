"""Request-body shape validation (validation priority 5: ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from timeutil import parse_dt


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        _bad("request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        _bad("%s is required and must be a non-empty string" % field)
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if not isinstance(v, str) or v not in values:
        _bad("%s must be one of %s" % (field, ", ".join(sorted(values))))
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field, min_value=None, max_value=None):
    v = data.get(field)
    if not is_int(v):
        _bad("%s is required and must be an integer" % field)
    if min_value is not None and v < min_value:
        _bad("%s must be >= %d" % (field, min_value))
    if max_value is not None and v > max_value:
        _bad("%s must be <= %d" % (field, max_value))
    return v


def opt_int(data, field):
    """Optional integer field: absent/None -> None; present non-int -> 400."""
    if field not in data or data.get(field) is None:
        return None
    v = data.get(field)
    if not is_int(v):
        _bad("%s must be an integer" % field)
    return v


def req_dt(data, field):
    dt = parse_dt(data.get(field))
    if dt is None:
        _bad("%s is required and must be an ISO 8601 datetime" % field)
    return dt


def req_number(data, field):
    """A JSON number (int or float, not bool), returned as exact Decimal."""
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("%s is required and must be a number" % field)
    try:
        return Decimal(str(v))
    except InvalidOperation:
        _bad("%s must be a number" % field)
