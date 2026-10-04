"""Request body shape validation (pipeline stage 2 -> ERR_INVALID_REQUEST)."""
from flask import request

from dates import parse_dt
from errors import ApiError


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _bad(field):
    raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid or missing field: %s" % field)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        _bad(field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        _bad(field)
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field)
    return v


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field)
    return v


def req_num(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field)
    return v


def opt_num(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field)
    return v


def req_dt(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        _bad(field)
    try:
        return parse_dt(v)
    except Exception:
        _bad(field)


def opt_dt(data, field):
    if field not in data or data[field] is None:
        return None
    return req_dt(data, field)


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field)
    return v


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        _bad(field)
    return v


def req_obj(data, field):
    v = data.get(field)
    if not isinstance(v, dict):
        _bad(field)
    return v
