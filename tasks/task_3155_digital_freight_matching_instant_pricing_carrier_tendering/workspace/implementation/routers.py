"""Request-body helpers shared by every route module."""

from flask import request

from errors import ApiError


def body():
    """The JSON request body, or an empty mapping when none was sent."""
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data:
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be valid JSON.")
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def require(payload, *fields):
    for field in fields:
        if field not in payload or payload[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
    return payload


def require_int(payload, field, minimum=None):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be at least %d." % (field, minimum))
    return value


def enum(payload, field, allowed, required=True, default=None):
    if field not in payload or payload[field] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "%s is required." % field)
        return default
    value = payload[field]
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Unknown %s." % field)
    return value