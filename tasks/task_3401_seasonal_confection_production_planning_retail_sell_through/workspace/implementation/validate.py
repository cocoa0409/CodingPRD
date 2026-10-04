"""Syntactic request validation helpers.

Per PRD 2.8, syntactic validation (missing required field, wrong type,
out-of-enum value, violated field constraint) is rejected with
ERR_INVALID_REQUEST / 400 and runs before the numbered priorities.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_dt
from errors import ApiError, ERR_INVALID_REQUEST


def _bad(msg):
    return ApiError(400, ERR_INVALID_REQUEST, msg)


def json_body():
    """Return the request JSON object; 400 if absent or not a JSON object."""
    data = request.get_json(silent=True)
    if data is None:
        raise _bad("request body must be a JSON object")
    if not isinstance(data, dict):
        raise _bad("request body must be a JSON object")
    return data


def v_str(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise _bad("missing required field: %s" % name)
        return None
    val = data[name]
    if not isinstance(val, str) or isinstance(val, bool):
        raise _bad("field '%s' must be a string" % name)
    return val


def v_int(data, name, required=True, min_v=None):
    if name not in data or data[name] is None:
        if required:
            raise _bad("missing required field: %s" % name)
        return None
    val = data[name]
    # bool is a subclass of int in Python; JSON true/false is not an integer here
    if isinstance(val, bool) or not isinstance(val, int):
        raise _bad("field '%s' must be an integer" % name)
    if min_v is not None and val < min_v:
        raise _bad("field '%s' must be >= %s" % (name, min_v))
    return val


def v_bool(data, name, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise _bad("missing required field: %s" % name)
        return default
    val = data[name]
    if not isinstance(val, bool):
        raise _bad("field '%s' must be a boolean" % name)
    return val


def v_enum(data, name, allowed, required=True):
    val = v_str(data, name, required=required)
    if val is None:
        return None
    if val not in allowed:
        raise _bad("field '%s' must be one of %s" % (name, sorted(allowed)))
    return val


def v_dt(data, name, required=True):
    """Validate a datetime field; returns (parsed_datetime, raw_string)."""
    if name not in data or data[name] is None:
        if required:
            raise _bad("missing required field: %s" % name)
        return None, None
    parsed = parse_dt(data[name], name)
    return parsed, data[name]


def v_num(data, name, required=True):
    """Validate a JSON number (int or float, never bool); returns Decimal."""
    if name not in data or data[name] is None:
        if required:
            raise _bad("missing required field: %s" % name)
        return None
    val = data[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise _bad("field '%s' must be a number" % name)
    try:
        return Decimal(str(val))
    except InvalidOperation:
        raise _bad("field '%s' must be a number" % name)
