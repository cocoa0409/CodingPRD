"""Request-shape validation (ladder step 3).

Every violation is ERR_INVALID_REQUEST with HTTP 400: an unparseable body, a
missing required field, a wrong type, a value outside a declared enumeration, a
malformed ISO-8601 date or instant, or a broken declared field constraint.
Unknown fields are ignored rather than rejected.
"""

from flask import request

from core import parse_date, parse_instant
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body(required=True):
    """Parse the JSON body.  Returns {} when the request carries no body."""
    raw = request.get_data() or b""
    if raw.strip() == b"":
        if required:
            _bad("A JSON request body is required.")
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad("The request body is not valid JSON.")
    if not isinstance(payload, dict):
        _bad("The request body must be a JSON object.")
    return payload


def optional_body():
    return body(required=False)


def _present(payload, name):
    return name in payload and payload[name] is not None


def string_field(payload, name, required=True, default=None, non_empty=False):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    if non_empty and value.strip() == "":
        _bad("Field '%s' must not be empty." % name)
    return value


def integer_field(payload, name, required=True, default=None, minimum=None,
                  maximum=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %d." % (name, maximum))
    return value


def boolean_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % name)
    return value


def enum_field(payload, name, members, required=True, default=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in members:
        _bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def date_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    parsed = parse_date(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO-8601 calendar date (YYYY-MM-DD)." % name)
    return parsed


def instant_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    parsed = parse_instant(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO-8601 UTC instant." % name)
    return parsed


def enum_array_field(payload, name, members, required=False, default=None):
    if not _present(payload, name):
        if required:
            _bad("Field '%s' is required." % name)
        return list(default or [])
    value = payload[name]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in members:
            _bad(
                "Field '%s' may only contain %s." % (name, ", ".join(members))
            )
    return list(value)


def branch_code(value):
    if not (2 <= len(value) <= 8):
        _bad("branch_code must be between 2 and 8 characters.")
    if value != value.upper():
        _bad("branch_code must be uppercase.")
    return value
