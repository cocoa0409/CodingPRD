"""Request-body parsing and field validation helpers (priority 25/26 checks)."""
from flask import request

from errors import ApiError

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def body_or_fail():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def raw(name, default=MISSING):
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or name not in data or data[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    return data[name]


def text_field(source, name, default=MISSING, allow_empty=False):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string" % name)
    value = value.strip()
    if not value and not allow_empty:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must not be empty" % name)
        return default
    return value


def enum_field(source, name, allowed, default=MISSING):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s" % (name, ", ".join(allowed)),
        )
    return value


def bool_field(source, name, default=MISSING):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % name)


def num_field(source, name, default=MISSING):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number" % name)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number" % name)
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number" % name)


def int_field(source, name, default=MISSING):
    value = num_field(source, name, default)
    if value is default:
        return value
    if float(value) != int(value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % name)
    return int(value)


def datetime_field(source, name, default=MISSING):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 string" % name)
    from db import parse_iso

    parsed = parse_iso(value)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant" % name)
    return value


def date_field(source, name, default=MISSING):
    if name not in source or source[name] is None:
        if default is MISSING:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'" % name)
        return default
    value = source[name]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date" % name)
    from db import parse_date

    if parse_date(value) is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date" % name)
    return value


def require_min_length(value, minimum, error_id="ERR_JUSTIFICATION_TOO_SHORT"):
    if value is None or len(value) < minimum:
        raise ApiError(error_id, "Text must be at least %d characters" % minimum)
    return value