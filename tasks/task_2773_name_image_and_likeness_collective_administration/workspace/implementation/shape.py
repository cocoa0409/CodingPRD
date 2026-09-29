"""Priority-5 request shape validation (PRD 2.8).

One pass covers required fields, declared types, declared enum values, the
positive-money rules, the bounded-integer rules and ISO-8601 timestamps.
Unknown body fields are ignored rather than rejected.
"""

from flask import request

import clock
from errors import ApiError


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def _missing(name):
    raise ApiError("ERR_INVALID_REQUEST", "%s is required." % name)


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s." % (name, why))


def string_field(data, name, required=False, default=None, allow_empty=False):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def enum_field(data, name, allowed, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def int_field(data, name, required=False, default=None, minimum=None,
              maximum=None, positive=False):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if positive and value <= 0:
        _bad(name, "must be strictly greater than zero")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def bool_field(data, name, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def ts_field(data, name, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            _missing(name)
        return default
    return clock.parse_ts(data[name], name)


def forbid_present(data, name, message):
    if name in data and data[name] is not None:
        raise ApiError("ERR_INVALID_REQUEST", message)
