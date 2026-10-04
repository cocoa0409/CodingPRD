"""Request-body shape validation (validation tier 4, PRD 2.8).

Every failure here surfaces as ERR_INVALID_REQUEST (400) unless a more specific
error is pinned elsewhere (ERR_INVALID_WINDOW / ERR_FUTURE_PERIOD live in
timeutil / route code).
"""
from flask import request

from errors import api_err
from money import to_decimal
from timeutil import parse_iso, parse_period


def body():
    """Return the JSON request body as a dict; a missing body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise api_err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _bad(field, why):
    raise api_err("ERR_INVALID_REQUEST", "field '{}': {}".format(field, why))


def req_field(data, name):
    if name not in data or data[name] is None:
        _bad(name, "is required")
    return data[name]


def opt_field(data, name):
    """Return the field value, or None when absent (explicit null is kept)."""
    return data.get(name)


def as_str(value, field, allow_empty=False):
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and value == "":
        _bad(field, "must not be empty")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    return value


def as_number(value, field):
    """JSON number -> Decimal."""
    try:
        return to_decimal(value)
    except ValueError:
        _bad(field, "must be a number")


def as_bool(value, field):
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def as_list(value, field):
    if not isinstance(value, list):
        _bad(field, "must be an array")
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of {}".format(sorted(allowed)))
    return value


def as_datetime(value, field):
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        _bad(field, "must be an ISO-8601 datetime string")


def as_period(value, field):
    try:
        return parse_period(value)
    except ValueError as exc:
        _bad(field, str(exc))


def as_str_list(value, field):
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _bad(field, "must be an array of strings")
    return value
