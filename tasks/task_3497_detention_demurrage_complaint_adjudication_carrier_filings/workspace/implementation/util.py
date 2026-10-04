"""Request-body shape helpers (validation-ladder rung 6)."""
from flask import request

from clock import parse_iso
from errors import fail, ERR_INVALID_REQUEST


def body():
    """Parse the JSON request body; a missing body behaves as {} (required-field
    checks then fire), a non-object body is a shape error."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_field(d, name, err=ERR_INVALID_REQUEST):
    v = d.get(name)
    if v is None:
        fail(err, "missing required field: %s" % name)
    return v


def req_str(d, name, err=ERR_INVALID_REQUEST):
    v = req_field(d, name, err)
    if not isinstance(v, str) or v == "":
        fail(ERR_INVALID_REQUEST, "field %s must be a non-empty string" % name)
    return v


def opt_str(d, name):
    v = d.get(name)
    if v is not None and not isinstance(v, str):
        fail(ERR_INVALID_REQUEST, "field %s must be a string" % name)
    return v


def req_int(d, name, lo=None, hi=None, err=ERR_INVALID_REQUEST):
    v = req_field(d, name, err)
    if not is_int(v):
        fail(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    if lo is not None and v < lo:
        fail(ERR_INVALID_REQUEST, "field %s must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        fail(ERR_INVALID_REQUEST, "field %s must be <= %d" % (name, hi))
    return v


def opt_int(d, name, default, lo=None, hi=None):
    v = d.get(name)
    if v is None:
        return default
    if not is_int(v):
        fail(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    if lo is not None and v < lo:
        fail(ERR_INVALID_REQUEST, "field %s must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        fail(ERR_INVALID_REQUEST, "field %s must be <= %d" % (name, hi))
    return v


def req_enum(d, name, allowed, err=ERR_INVALID_REQUEST):
    v = req_field(d, name, err)
    if not isinstance(v, str) or v not in allowed:
        fail(ERR_INVALID_REQUEST,
             "field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def req_dt(d, name, missing_err=ERR_INVALID_REQUEST, invalid_err=ERR_INVALID_REQUEST):
    v = req_field(d, name, missing_err)
    try:
        dt, _frac = parse_iso(v)
    except (ValueError, TypeError):
        fail(invalid_err, "field %s is not a valid ISO-8601 timestamp" % name)
    return dt
