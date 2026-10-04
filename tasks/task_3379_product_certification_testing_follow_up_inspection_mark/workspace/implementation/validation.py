"""Request payload validation helpers. Missing required fields, wrong types,
and invalid enum values raise ERR_INVALID_REQUEST (HTTP 400), which PRD 2.8
places separately from the ordered pipeline."""
from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST


def body(required=False):
    """Return the JSON request body as a dict. Any POST that declares inputs
    requires a JSON object body."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def _fail(field, why):
    raise ApiError(ERR_INVALID_REQUEST, "field '%s' %s" % (field, why))


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or value == "":
        _fail(field, "is required and must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    value = data.get(field, default)
    if value is not None and not isinstance(value, str):
        _fail(field, "must be a string")
    return value


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        _fail(field, "is required and must be a boolean")
    return value


def req_int(data, field, minimum=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "is required and must be an integer")
    if minimum is not None and value < minimum:
        _fail(field, "must be >= %d" % minimum)
    return value


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum=minimum)


def req_number(data, field):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field, "is required and must be a number")
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        _fail(field, "must be one of: %s" % ", ".join(allowed))
    return value


def req_list(data, field):
    value = data.get(field)
    if not isinstance(value, list):
        _fail(field, "is required and must be an array")
    return value


def opt_list(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_list(data, field)


def req_str_list(data, field):
    value = req_list(data, field)
    for item in value:
        if not isinstance(item, str):
            _fail(field, "must contain only strings")
    return value


def opt_str_list(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_str_list(data, field)


def req_datetime(data, field):
    raw = data.get(field)
    if not isinstance(raw, str):
        _fail(field, "is required and must be an ISO 8601 datetime string")
    parsed = clock.parse_iso(raw)
    if parsed is None:
        _fail(field, "must be a valid ISO 8601 datetime")
    return parsed


def opt_datetime(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_datetime(data, field)


def req_object(data, field):
    value = data.get(field)
    if not isinstance(value, dict):
        _fail(field, "is required and must be an object")
    return value
