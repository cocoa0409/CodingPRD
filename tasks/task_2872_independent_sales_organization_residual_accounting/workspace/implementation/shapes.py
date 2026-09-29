"""Band 4 request-shape helpers and band 5 field-domain helpers."""
from decimal import Decimal, InvalidOperation

from flask import request

from apierrors import fail
from store import is_month, parse_date


def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def supplied(payload, name):
    return name in payload


def present(payload, name):
    return name in payload and payload[name] is not None


def _missing(name):
    fail("ERR_INVALID_REQUEST", "%s is required" % name)


def as_str(payload, name, required=True, min_len=None, max_len=None, default=None):
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters" % (name, max_len))
    return value


def as_int(payload, name, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, maximum))
    return value


def as_decimal(payload, name, required=True, default=None):
    """A JSON number carried as an exact Decimal."""
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    try:
        return Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)


def as_enum(payload, name, allowed, required=True, default=None):
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def as_date(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a date-only string" % name)
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date" % name)
    return value


def as_month_string(payload, name, required=True, default=None):
    """Band 4: the value must be present and a string. The YYYY-MM shape is band 5."""
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return value


def as_id(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            _missing(name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string identifier" % name)
    return value


def check_month(value, name):
    """Band 5: ERR_INVALID_PERIOD_MONTH."""
    if value is None:
        return None
    if not is_month(value):
        fail("ERR_INVALID_PERIOD_MONTH", "%s must match YYYY-MM with month 01..12" % name)
    return value


def check_pct_range(value, name):
    """Band 5: closed interval [0, 1] -> ERR_INVALID_PCT_RANGE."""
    if value is None:
        return None
    if value < Decimal("0") or value > Decimal("1"):
        fail("ERR_INVALID_PCT_RANGE", "%s must lie in the closed interval [0, 1]" % name)
    return value
