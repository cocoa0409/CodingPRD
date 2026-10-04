"""Field-shape validation helpers (validation priority 10 -> ERR_VALIDATION 400).

These run LAST in each endpoint, after auth/ownership/existence/OCC/state/
compliance/constraint/temporal gates, per PRD 2.9 error precedence.
"""
from flask import request

from db import parse_dt
from errors import err


def body():
    """Request JSON object; absent/malformed JSON behaves as an empty object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _missing(data, name):
    return name not in data or data[name] is None


def as_str(data, name, required=True):
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    if not isinstance(data[name], str):
        err("ERR_VALIDATION", 400, "Field %s must be a string" % name)
    return data[name]


def as_bool(data, name, required=True):
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    if not isinstance(data[name], bool):
        err("ERR_VALIDATION", 400, "Field %s must be a boolean" % name)
    return data[name]


def as_int(data, name, required=True, minimum=None, maximum=None):
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 400, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 400, "Field %s must be <= %s" % (name, maximum))
    return v


def as_number(data, name, required=True, minimum=None, maximum=None):
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 400, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 400, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 400, "Field %s must be <= %s" % (name, maximum))
    return v


def as_enum(data, name, allowed, required=True):
    v = as_str(data, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        err("ERR_VALIDATION", 400, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def as_list(data, name, required=True):
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    if not isinstance(data[name], list):
        err("ERR_VALIDATION", 400, "Field %s must be an array" % name)
    return data[name]


def as_enum_list(data, name, allowed, required=True):
    items = as_list(data, name, required=required)
    if items is None:
        return None
    for item in items:
        if not isinstance(item, str) or item not in allowed:
            err("ERR_VALIDATION", 400,
                "Field %s elements must be one of %s" % (name, sorted(allowed)))
    return items


def as_str_list(data, name, required=True):
    items = as_list(data, name, required=required)
    if items is None:
        return None
    for item in items:
        if not isinstance(item, str):
            err("ERR_VALIDATION", 400, "Field %s elements must be strings" % name)
    return items


def as_dt(data, name, required=True):
    """Parse an ISO8601 field; ERR_VALIDATION on missing/unparseable."""
    if _missing(data, name):
        if required:
            err("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    dt = parse_dt(data[name])
    if dt is None:
        err("ERR_VALIDATION", 400, "Field %s must be an ISO8601 timestamp" % name)
    return dt
