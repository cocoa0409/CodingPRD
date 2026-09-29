"""Request-shape validation (PRD 2.8 step 3), number format (step 4) and
interval well-ordering (step 5)."""
import re
from decimal import Decimal

from flask import request

import errors
import store

# PRD 2.8 step 4: a leading '+' followed by 11 to 15 digits.
E164_RE = re.compile(r"^\+\d{11,15}$")


def body():
    """Parsed JSON object body; ERR_INVALID_REQUEST when malformed."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return payload


def _bad(field, why):
    errors.fail(errors.ERR_INVALID_REQUEST, "%s %s" % (field, why))


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value == "":
        _bad(field, "must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value == "":
        _bad(field, "must be a non-empty string")
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _bad(field, "is not a declared enum member")
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = req_str(data, field)
    if value not in allowed:
        _bad(field, "is not a declared enum member")
    return value


def req_int(data, field, minimum=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d" % minimum)
    return value


def req_count(data, field):
    """A count field: integer, never negative (PRD 2.8 step 3)."""
    return req_int(data, field, minimum=0)


def req_score(data, field):
    """Four-decimal score in [0.0000, 1.0000] inclusive (PRD 2.7)."""
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    dec = Decimal(str(value))
    if dec < Decimal("0") or dec > Decimal("1"):
        _bad(field, "must lie within 0.0000 and 1.0000 inclusive")
    return dec


def req_dt(data, field):
    """Returns (datetime, raw_string)."""
    if not present(data, field):
        _bad(field, "is required")
    raw = data[field]
    parsed = store.parse_iso(raw)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return parsed, raw


def opt_dt(data, field):
    if not present(data, field):
        return None, None
    return req_dt(data, field)


def req_enum_list(data, field, allowed):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for element in value:
        if not isinstance(element, str) or element not in allowed:
            _bad(field, "contains an undeclared enum member")
    return list(value)


def req_str_list(data, field, min_len=1):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, list) or len(value) < min_len:
        _bad(field, "must be an array with at least %d element(s)" % min_len)
    for element in value:
        if not isinstance(element, str) or element == "":
            _bad(field, "must contain non-empty strings")
    return list(value)


def check_e164(*numbers):
    """PRD 2.8 step 4 -> ERR_INVALID_NUMBER_FORMAT (422)."""
    for number in numbers:
        if number is None:
            continue
        if not E164_RE.match(number):
            errors.fail(errors.ERR_INVALID_NUMBER_FORMAT,
                        "%s is not a well-formed E.164 number" % number)


def check_interval(start, end):
    """PRD 2.8 step 5 -> ERR_INVALID_INTERVAL (422)."""
    if start is None or end is None:
        return
    if not start < end:
        errors.fail(errors.ERR_INVALID_INTERVAL,
                    "The supplied interval is not well ordered")


def arg_enum(name, allowed):
    """Validate an optional query-string filter against its enum."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        _bad(name, "is not a declared enum member")
    return raw


def arg_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
