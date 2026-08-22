"""Request-shape validation (PRD order-of-rejection step 3)."""
from decimal import InvalidOperation

from flask import request

import dates
from errors import invalid
from money import D, decimal_places

_MISSING = object()


def body():
    if request.content_length in (None, 0) and not request.data:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        if request.data:
            raise invalid("Request body must be a JSON object.")
        return {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def present(data, key):
    return key in data and data[key] is not None


def get_string(data, key, required=False, max_len=None, non_empty=True, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if non_empty and value.strip() == "":
        raise invalid("Field '%s' must not be empty." % key)
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' exceeds %d characters." % (key, max_len))
    return value


def get_enum(data, key, allowed, required=False, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def get_bool(data, key, required=False, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def get_int(data, key, required=False, default=None, minimum=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be at least %d." % (key, minimum))
    return value


def get_decimal(data, key, places, required=False, default=None,
                positive=False, non_negative=False):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field '%s' must be a number." % key)
    try:
        parsed = D(value)
    except (InvalidOperation, ValueError):
        raise invalid("Field '%s' must be a number." % key)
    if not parsed.is_finite():
        raise invalid("Field '%s' must be a finite number." % key)
    if decimal_places(parsed) > places:
        raise invalid("Field '%s' allows at most %d decimal places." % (key, places))
    if positive and parsed <= 0:
        raise invalid("Field '%s' must be greater than zero." % key)
    if non_negative and parsed < 0:
        raise invalid("Field '%s' must not be negative." % key)
    return parsed


def get_date(data, key, required=False, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    parsed = dates.parse_date(value)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO YYYY-MM-DD date." % key)
    return parsed


def get_id(data, key, required=False, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("Field '%s' must be an identifier string." % key)
    return value


def get_time_of_day(data, key, required=False, default=None):
    if not present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or not dates.TIME_RE.match(value):
        raise invalid("Field '%s' must be an HH:MM:SS 24-hour time." % key)
    return value


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' is not a recognised value." % name)
    return value


def query_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    if dates.parse_date(value) is None:
        raise invalid("Query parameter '%s' must be an ISO YYYY-MM-DD date." % name)
    return value
