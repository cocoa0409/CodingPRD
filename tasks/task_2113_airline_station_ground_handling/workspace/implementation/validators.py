"""Request-shape validation (order-of-evaluation step 4) -> ERR_INVALID_REQUEST."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_iso

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def present(payload, field):
    return field in payload and payload[field] is not None


def req_string(payload, field):
    if not present(payload, field):
        _bad(field, "is required.")
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        _bad(field, "must be a non-empty string.")
    return value


def opt_string(payload, field, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    return value


def req_enum(payload, field, allowed):
    value = req_string(payload, field)
    if value not in allowed:
        _bad(field, "must be one of %s." % ", ".join(allowed))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s." % ", ".join(allowed))
    return value


def _check_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s." % maximum)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    if not present(payload, field):
        _bad(field, "is required.")
    return _check_int(field, payload[field], minimum, maximum)


def opt_int(payload, field, default=None, minimum=None, maximum=None):
    if not present(payload, field):
        return default
    return _check_int(field, payload[field], minimum, maximum)


def _check_decimal(field, value, minimum, maximum, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number.")
    if minimum is not None:
        if exclusive_min and number <= minimum:
            _bad(field, "must be greater than %s." % minimum)
        if not exclusive_min and number < minimum:
            _bad(field, "must be >= %s." % minimum)
    if maximum is not None and number > maximum:
        _bad(field, "must be <= %s." % maximum)
    return number


def opt_decimal(payload, field, default=None, minimum=None, maximum=None, exclusive_min=False):
    if not present(payload, field):
        return default
    return _check_decimal(field, payload[field], minimum, maximum, exclusive_min)


def req_datetime(payload, field):
    if not present(payload, field):
        _bad(field, "is required.")
    raw = payload[field]
    try:
        parse_iso(raw)
    except (ValueError, TypeError):
        _bad(field, "must be an ISO 8601 instant.")
    return raw


def opt_datetime(payload, field, default=None):
    if not present(payload, field):
        return default
    raw = payload[field]
    try:
        parse_iso(raw)
    except (ValueError, TypeError):
        _bad(field, "must be an ISO 8601 instant.")
    return raw


def forbid(payload, field):
    if present(payload, field):
        _bad(field, "must not be supplied for this resource family.")
