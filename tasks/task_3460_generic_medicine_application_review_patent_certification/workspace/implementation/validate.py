"""Request body shape checks (pipeline priority 5).

Unknown payload fields and client-supplied system/computed fields (id,
created_at, version, is_adequate, status, ...) are ignored: never echoed,
never rejected. These helpers only read the fields they are asked for.
"""
from flask import request

from clock import parse_date
from errors import fail


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s" % (name, why))


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        _bad(name, "is required and must be a string")
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, str):
        _bad(name, "must be a string or null")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        _bad(name, "is required and must be a boolean")
    return v


def opt_bool(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def req_number(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(name, "is required and must be a number")
    return v


def req_int(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "is required and must be an integer")
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        _bad(name, "is required and must be one of %s" % "|".join(allowed))
    return v


def opt_enum(b, name, allowed, default=None):
    v = b.get(name, default)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        _bad(name, "must be one of %s" % "|".join(allowed))
    return v


def req_date(b, name):
    v = b.get(name)
    try:
        return parse_date(v)
    except ValueError:
        _bad(name, "is required and must be a YYYY-MM-DD date")


def req_str_list(b, name):
    v = b.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(name, "is required and must be an array of strings")
    return v


def opt_str_list(b, name, default=None):
    v = b.get(name, default)
    if v is None:
        return default
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _bad(name, "must be an array of strings")
    return v
