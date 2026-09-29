"""Request-shape validation: check 9 of PRD 2.6 (ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

from clock import parse_instant
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


def req_int(payload, field, lo=None, hi=None):
    if not present(payload, field):
        bad("%s is required." % field)
    return as_int(payload[field], field, lo, hi)


def opt_int(payload, field, lo=None, hi=None, default=None):
    if not present(payload, field):
        return default
    return as_int(payload[field], field, lo, hi)


def as_int(value, field, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % field)
    if lo is not None and value < lo:
        bad("%s must be at least %s." % (field, lo))
    if hi is not None and value > hi:
        bad("%s must be at most %s." % (field, hi))
    return value


def req_str(payload, field, min_len=1, max_len=None):
    if not present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if min_len is not None and len(value.strip()) < min_len:
        bad("%s must not be blank." % field)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (field, max_len))
    return value


def opt_str(payload, field, max_len=None, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad("%s must be a string." % field)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (field, max_len))
    return value


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        bad("%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def req_id(payload, field):
    if not present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be an identifier string." % field)
    return value


def opt_id(payload, field):
    if not present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be an identifier string." % field)
    return value


def req_instant(payload, field):
    if not present(payload, field):
        bad("%s is required." % field)
    parsed = parse_instant(payload[field])
    if parsed is None:
        bad("%s must be an ISO 8601 instant with an explicit UTC offset." % field)
    return parsed


def opt_instant(payload, field):
    if not present(payload, field):
        return None
    parsed = parse_instant(payload[field])
    if parsed is None:
        bad("%s must be an ISO 8601 instant with an explicit UTC offset." % field)
    return parsed


def to_decimal(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s must be a number." % field)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number." % field)
    if not dec.is_finite():
        bad("%s must be a finite number." % field)
    return dec


def req_percentage(payload, field, lo, hi, places=2):
    if not present(payload, field):
        bad("%s is required." % field)
    dec = to_decimal(payload[field], field)
    if dec < Decimal("0") or dec > Decimal("1"):
        bad("%s must be between 0 and 1." % field)
    if dec < Decimal(str(lo)) or dec > Decimal(str(hi)):
        bad("%s must be between %s and %s." % (field, lo, hi))
    if -dec.as_tuple().exponent > places:
        bad("%s carries at most %d decimal places." % (field, places))
    return dec


def req_list(payload, field, min_len=1, max_len=None):
    if not present(payload, field):
        bad("%s is required." % field)
    value = payload[field]
    if not isinstance(value, list):
        bad("%s must be an array." % field)
    if min_len is not None and len(value) < min_len:
        bad("%s must not be empty." % field)
    if max_len is not None and len(value) > max_len:
        bad("%s must carry at most %d elements." % (field, max_len))
    return value


def forbid(payload, field, reason):
    if field in payload and payload[field] is not None:
        bad("%s is forbidden %s." % (field, reason))
