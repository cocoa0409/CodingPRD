"""Request-shape validation (ladder priority 3).

Every extractor raises `ERR_INVALID_REQUEST` (HTTP 400) on a missing required
field, a value of the wrong type, an enum outside its declared set, or a
malformed date or datetime.
"""
import re

from errors import ApiError
from util import parse_date, parse_dt

_MISSING = object()

LOWER3 = re.compile(r"^[a-z]{3}$")
UPPER3 = re.compile(r"^[A-Z]{3}$")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_of(request):
    """The JSON request body as a dict; absent bodies read as empty."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def _fetch(body, field, required):
    if field not in body or body[field] is None:
        if required:
            raise bad("Field '%s' is required." % field)
        return _MISSING
    return body[field]


def str_field(body, field, required=True, default=None, pattern=None, label=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be a non-empty string." % field)
    if pattern is not None and not pattern.match(value):
        raise bad("Field '%s' does not match its required format%s." % (
            field, (" (" + label + ")") if label else ""))
    return value


def int_field(body, field, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % field)
    _range_check(field, value, minimum, maximum)
    return value


def num_field(body, field, required=True, default=None, minimum=None, maximum=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % field)
    _range_check(field, value, minimum, maximum)
    return value


def _range_check(field, value, minimum, maximum):
    if minimum is not None and value < minimum:
        raise bad("Field '%s' may not be below %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' may not exceed %s." % (field, maximum))


def bool_field(body, field, required=True, default=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % field)
    return value


def enum_field(body, field, allowed, required=True, default=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def date_field(body, field, required=True, default=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    parsed = parse_date(value)
    if parsed is None:
        raise bad("Field '%s' must be a YYYY-MM-DD date." % field)
    return parsed


def datetime_field(body, field, required=True, default=None):
    value = _fetch(body, field, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    return parsed


def query_enum(args, field, allowed):
    """An optional enum-valued query filter."""
    value = args.get(field)
    if value is None:
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def query_date(args, field):
    value = args.get(field)
    if value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        raise bad("Query parameter '%s' must be a YYYY-MM-DD date." % field)
    return parsed


def query_str(args, field):
    value = args.get(field)
    if value is None:
        return None
    return value
