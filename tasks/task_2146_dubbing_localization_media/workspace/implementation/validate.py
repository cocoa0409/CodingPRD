"""Body field validation (PRD section 2.6 rung 8 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import ApiError
from store import parse_iso

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(key, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


def _fetch(data, key, required, default):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return _MISSING if default is _MISSING else default
    return data[key]


def v_string(data, key, required=True, default=None, non_empty=True):
    value = _fetch(data, key, required, default)
    if value is _MISSING or (not required and key not in data):
        return value if value is not _MISSING else default
    if value is None:
        return None
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if non_empty and value.strip() == "":
        _bad(key, "must be non-empty")
    return value


def v_int(data, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def v_number(data, key, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def v_bool(data, key, required=True, default=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def v_enum(data, key, allowed, required=True, default=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % (sorted(allowed),))
    return value


def v_object(data, key, required=True, default=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if not isinstance(value, dict):
        _bad(key, "must be an object")
    return value


def v_array(data, key, required=True, default=None, non_empty=False,
            member_enum=None, member_type=None, member_non_empty=False):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if not isinstance(value, list):
        _bad(key, "must be an array")
    if non_empty and len(value) == 0:
        _bad(key, "must be non-empty")
    for item in value:
        if member_enum is not None:
            if not isinstance(item, str) or item not in member_enum:
                _bad(key, "members must be one of %s" % (list(member_enum),))
        if member_type is str:
            if not isinstance(item, str):
                _bad(key, "members must be strings")
            if member_non_empty and item.strip() == "":
                _bad(key, "members must be non-empty strings")
        if member_type is dict and not isinstance(item, dict):
            _bad(key, "members must be objects")
    return value


def v_datetime(data, key, required=True, default=None):
    value = _fetch(data, key, required, default)
    if value is None:
        return None
    if not isinstance(value, str):
        _bad(key, "must be an ISO-8601 datetime string")
    parsed = parse_iso(value)
    if parsed is None:
        _bad(key, "must be an ISO-8601 datetime string")
    return parsed
