"""Request-shape validation helpers (ladder priority 5)."""

from fractions import Fraction

from flask import request

import store
from errors import invalid

MISSING = object()


def body():
    """The parsed JSON object of the request, or {} when there is none.

    A malformed or non-object payload is a request-shape failure, but it must
    never pre-empt the path-existence rung, so parsing is deferred until a
    handler explicitly asks for the body.
    """
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw and raw.strip():
            invalid("The request body is not valid JSON.")
        return {}
    if not isinstance(data, dict):
        invalid("The request body must be a JSON object.")
    return data


def _raw(data, name):
    return data.get(name, MISSING)


def present(data, name):
    value = _raw(data, name)
    return value is not MISSING and value is not None


def str_field(data, name, required=True, allow_empty=False, max_len=None,
              default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    if not isinstance(value, str):
        invalid("%s must be a string." % name)
    if not allow_empty and not value.strip():
        invalid("%s must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        invalid("%s must be at most %d characters." % (name, max_len))
    return value


def int_field(data, name, required=True, minimum=None, maximum=None,
              default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("%s must be at most %d." % (name, maximum))
    return value


def number_field(data, name, required=True, minimum=None, default=None):
    """A non-negative decimal quantity such as labor_hours."""
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("%s must be a number." % name)
    try:
        exact = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        invalid("%s must be a number." % name)
    if minimum is not None and exact < minimum:
        invalid("%s must be at least %s." % (name, minimum))
    return exact


def enum_field(data, name, allowed, required=True, default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    if not isinstance(value, str) or value not in allowed:
        invalid("%s must be one of: %s." % (name, ", ".join(sorted(allowed))))
    return value


def bool_field(data, name, required=False, default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    if not isinstance(value, bool):
        invalid("%s must be a boolean." % name)
    return value


def date_field(data, name, required=True, default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    parsed = store.parse_date(value)
    if parsed is None:
        invalid("%s must be a calendar date in YYYY-MM-DD form." % name)
    return parsed


def instant_field(data, name, required=True, default=None):
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return default
    parsed = store.parse_instant(value)
    if parsed is None:
        invalid("%s must be an ISO 8601 UTC instant." % name)
    return parsed


def id_field(data, name, required=True):
    """A foreign-key string; existence is checked separately at priority 4."""
    value = _raw(data, name)
    if value is MISSING or value is None:
        if required:
            invalid("%s is required." % name)
        return None
    if not isinstance(value, str) or not value.strip():
        invalid("%s must be a non-empty string." % name)
    return value
