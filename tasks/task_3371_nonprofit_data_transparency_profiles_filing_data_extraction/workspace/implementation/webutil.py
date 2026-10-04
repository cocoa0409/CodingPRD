"""Request-body helpers: presence, typing and undeclared-field rejection.

PRD 2.10 rung 4: missing or ill-typed required body fields, body fields not
declared in the endpoint's input list, unknown enum members and out-of-range
numerics all yield ERR_INVALID_REQUEST (HTTP 400).
"""

from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST


def body():
    """The JSON request body, or an empty mapping when none was supplied."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def reject_unknown(data, allowed):
    for key in data:
        if key not in allowed:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field '%s' is not declared for this endpoint." % key,
            )


def require(data, names):
    for name in names:
        if name not in data or data[name] is None:
            raise ApiError(
                ERR_INVALID_REQUEST, "Field '%s' is required." % name
            )


def optional(data, name, default=None):
    value = data.get(name)
    return default if value is None else value


def as_string(data, name, required=True, allow_empty=False):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    if not allow_empty and value == "":
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must not be empty." % name)
    return value


def as_enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))),
        )
    return value


def as_int(data, name, required=True, default=None, minimum=None):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field '%s' must be at least %d." % (name, minimum),
        )
    return value


def as_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % name)
    return value


def as_datetime(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str) or clock.parse_dt(value) is None:
        raise ApiError(
            ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 timestamp." % name
        )
    return value


def as_list(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
    return value
