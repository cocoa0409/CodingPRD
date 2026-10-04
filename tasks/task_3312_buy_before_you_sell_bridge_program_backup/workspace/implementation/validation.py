"""Input extraction and range validation (PRD 2.11, priority 5).

These helpers implement the "payload is inspected for missing required fields
and for values outside their declared types and ranges, all of which produce
ERR_INVALID_REQUEST" rule.  They are deliberately strict: an integer field
declared in the PRD must arrive as a JSON integer, never a float or a numeric
string, because PRD 2.4 states that no monetary field is ever a decimal number
or a string.
"""

from errors import ERR_INVALID_REQUEST, ApiError
from timeutil import parse_iso

_MISSING = object()


def _bad(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def body_of(payload):
    """Return the request body as a dict, or an empty dict when absent."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _bad("The request body must be a JSON object.")
    return payload


def require(data, field):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        _bad("Field '%s' is required." % field)
    return value


def get_str(data, field, required=True, default=None, allow_empty=False):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if not required:
            return default
        _bad("Field '%s' is required." % field)
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        _bad("Field '%s' must not be empty." % field)
    return value


def get_int(data, field, required=True, default=None, minimum=None, maximum=None,
            exclusive_minimum=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if not required:
            return default
        _bad("Field '%s' is required." % field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be at most %d." % (field, maximum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad("Field '%s' must be greater than %d." % (field, exclusive_minimum))
    return value


def get_bool(data, field, required=True, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if not required:
            return default
        _bad("Field '%s' is required." % field)
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field)
    return value


def get_enum(data, field, allowed, required=True, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if not required:
            return default
        _bad("Field '%s' is required." % field)
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def get_datetime(data, field, required=True, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if not required:
            return default
        _bad("Field '%s' is required." % field)
    parsed = parse_iso(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 timestamp." % field)
    return parsed