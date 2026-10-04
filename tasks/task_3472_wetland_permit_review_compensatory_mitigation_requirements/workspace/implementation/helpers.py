"""Request-body field validation utilities (pipeline tier 6: request shape).

All shape failures raise ERR_INVALID_REQUEST (400). Optional fields treat an
explicit JSON null the same as absent.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_iso
from errors import api_err

RESOURCE_TYPES = ("EMERGENT_MARSH", "FORESTED_WETLAND", "OPEN_WATER", "STREAM")

_MISSING = object()


def get_body():
    """Return the JSON request body as a dict; a missing body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _fetch(body, name, required, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s is required" % name)
        return default
    return value


def req_str(body, name):
    value = _fetch(body, name, True)
    if not isinstance(value, str):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    return value


def opt_str(body, name, default=None):
    value = _fetch(body, name, False, default)
    if value is not default and value is not None and not isinstance(value, str):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    return value


def req_enum(body, name, values):
    value = _fetch(body, name, True)
    if value not in values:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be one of %s" % (name, ", ".join(values)))
    return value


def opt_enum(body, name, values, default=None):
    value = _fetch(body, name, False, default)
    if value is not default and value not in values:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be one of %s" % (name, ", ".join(values)))
    return value


def to_decimal(value, name):
    """Coerce a JSON number to Decimal; booleans and non-numbers rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be a number" % name)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be a number" % name)
    if result.is_nan() or result.is_infinite():
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be a finite number" % name)
    return result


def req_number(body, name, minimum=None, min_exclusive=False):
    value = to_decimal(_fetch(body, name, True), name)
    if minimum is not None:
        if min_exclusive and not value > minimum:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s must be > %s" % (name, minimum))
        if not min_exclusive and not value >= minimum:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s must be >= %s" % (name, minimum))
    return value


def opt_number(body, name, default=None, minimum=None, min_exclusive=False):
    raw = _fetch(body, name, False, _MISSING)
    if raw is _MISSING:
        return default
    value = to_decimal(raw, name)
    if minimum is not None:
        if min_exclusive and not value > minimum:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s must be > %s" % (name, minimum))
        if not min_exclusive and not value >= minimum:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s must be >= %s" % (name, minimum))
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = _fetch(body, name, True)
    if isinstance(value, bool) or not isinstance(value, int):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be <= %s" % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    value = _fetch(body, name, False, default)
    if value is default:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be <= %s" % (name, maximum))
    return value


def req_bool(body, name):
    value = _fetch(body, name, True)
    if not isinstance(value, bool):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    value = _fetch(body, name, False, default)
    if value is not default and not isinstance(value, bool):
        raise api_err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return value


def req_str_list(body, name, non_empty=False):
    value = _fetch(body, name, True)
    if not isinstance(value, list) or (non_empty and not value):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be a non-empty array" % name
                      if non_empty else "Field %s must be an array" % name)
    for item in value:
        if not isinstance(item, str):
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s must be an array of strings" % name)
    return value


def opt_datetime(body, name):
    raw = _fetch(body, name, False, None)
    if raw is None:
        return None
    try:
        return parse_iso(raw)
    except ValueError:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be an ISO 8601 timestamp" % name)


def req_datetime(body, name):
    raw = _fetch(body, name, True)
    try:
        return parse_iso(raw)
    except ValueError:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be an ISO 8601 timestamp" % name)


def parse_impacts(value, site_resource_types):
    """Validate an impacts array against the site's resource types.

    Each line: {resource_type, impact_acres}; resource_type must be one of the
    four declared types AND present in the site's resource_types_present;
    impact_acres must be a number > 0. Returns [(resource_type, Decimal)].
    """
    if not isinstance(value, list) or not value:
        raise api_err("ERR_INVALID_REQUEST",
                      "Field impacts must be a non-empty array")
    parsed = []
    for line in value:
        if not isinstance(line, dict):
            raise api_err("ERR_INVALID_REQUEST",
                          "Each impacts entry must be an object")
        rtype = line.get("resource_type")
        if rtype not in RESOURCE_TYPES:
            raise api_err("ERR_INVALID_REQUEST",
                          "impacts.resource_type must be one of %s"
                          % ", ".join(RESOURCE_TYPES))
        if rtype not in site_resource_types:
            raise api_err("ERR_INVALID_REQUEST",
                          "impacts.resource_type %s is not present on the site"
                          % rtype)
        if "impact_acres" not in line or line.get("impact_acres") is None:
            raise api_err("ERR_INVALID_REQUEST",
                          "impacts.impact_acres is required")
        acres = to_decimal(line.get("impact_acres"), "impacts.impact_acres")
        if not acres > 0:
            raise api_err("ERR_INVALID_REQUEST",
                          "impacts.impact_acres must be > 0")
        parsed.append((rtype, acres))
    return parsed
