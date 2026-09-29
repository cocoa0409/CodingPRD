"""Payload-shape validation (PRD 2.11 step 6 -> ERR_VALIDATION)."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return payload


def _fail(field, detail):
    raise ApiError("ERR_VALIDATION", "%s %s" % (field, detail))


def _present(payload, field):
    return field in payload and payload[field] is not None


def raw_fk(payload, field):
    """Return an FK candidate for existence checking, or None when unusable."""
    value = payload.get(field)
    if isinstance(value, str) and value != "":
        return value
    return None


def req_string(payload, field, min_len=1, max_len=None):
    if field not in payload:
        _fail(field, "is required.")
    value = payload[field]
    if not isinstance(value, str):
        _fail(field, "must be a string.")
    return _check_len(field, value, min_len, max_len)


def opt_string(payload, field, min_len=1, max_len=None, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        _fail(field, "must be a string.")
    return _check_len(field, value, min_len, max_len)


def _check_len(field, value, min_len, max_len):
    if min_len is not None and len(value) < min_len:
        _fail(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _fail(field, "must be at most %d characters." % max_len)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    if field not in payload:
        _fail(field, "is required.")
    return _as_int(field, payload[field], minimum, maximum)


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if not _present(payload, field):
        return default
    return _as_int(field, payload[field], minimum, maximum)


def _as_int(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _fail(field, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        _fail(field, "must be at most %d." % maximum)
    return value


def req_decimal(payload, field, minimum=None, maximum=None):
    if field not in payload:
        _fail(field, "is required.")
    return _as_decimal(field, payload[field], minimum, maximum)


def opt_decimal(payload, field, minimum=None, maximum=None, default=None):
    if not _present(payload, field):
        return default
    return _as_decimal(field, payload[field], minimum, maximum)


def _as_decimal(field, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(field, "must be a number.")
    try:
        parsed = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    except (InvalidOperation, ValueError):
        _fail(field, "must be a number.")
    if not parsed.is_finite():
        _fail(field, "must be a finite number.")
    if minimum is not None and parsed < Decimal(str(minimum)):
        _fail(field, "must be at least %s." % minimum)
    if maximum is not None and parsed > Decimal(str(maximum)):
        _fail(field, "must be at most %s." % maximum)
    return parsed


def req_enum(payload, field, allowed):
    if field not in payload:
        _fail(field, "is required.")
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _fail(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not _present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def req_bool(payload, field):
    if field not in payload:
        _fail(field, "is required.")
    value = payload[field]
    if not isinstance(value, bool):
        _fail(field, "must be a boolean.")
    return value


def opt_bool(payload, field, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        _fail(field, "must be a boolean.")
    return value


def req_date(payload, field):
    text = req_string(payload, field, min_len=1)
    parsed = parse_date(text)
    if parsed is None:
        _fail(field, "must be a date written YYYY-MM-DD.")
    return text, parsed


def req_instant(payload, field):
    text = req_string(payload, field, min_len=1)
    parsed = parse_instant(text)
    if parsed is None:
        _fail(field, "must be an ISO 8601 UTC instant.")
    return text, parsed


def req_enum_array(payload, field, allowed):
    if field not in payload:
        _fail(field, "is required.")
    value = payload[field]
    if not isinstance(value, list):
        _fail(field, "must be an array.")
    if len(value) == 0:
        _fail(field, "must be non-empty.")
    seen = []
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            _fail(field, "entries must be one of %s." % ", ".join(sorted(allowed)))
        if entry in seen:
            _fail(field, "must not contain duplicates.")
        seen.append(entry)
    return list(value)
