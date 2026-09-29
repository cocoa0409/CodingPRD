"""Request-shape validation (validation ladder rung 4)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import fail

TWO_UPPER = re.compile(r"^[A-Z]{2}$")
ELEVEN_DIGITS = re.compile(r"^\d{11}$")
SIX_DIGITS = re.compile(r"^\d{6}$")


def body():
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def _present(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def req_str(data, name, min_len=1, max_len=None, pattern=None):
    _present(data, name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d characters." % (name, max_len))
    if pattern is not None and not pattern.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' is malformed." % name)
    return value


def opt_str(data, name, min_len=1, max_len=None, pattern=None):
    if name not in data or data[name] is None:
        return None
    return req_str(data, name, min_len=min_len, max_len=max_len, pattern=pattern)


def req_int(data, name, min_value=None, max_value=None):
    _present(data, name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if min_value is not None and value < min_value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (name, min_value))
    if max_value is not None and value > max_value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (name, max_value))
    return value


def req_pct(data, name, min_value="0.00", max_value="100.00"):
    _present(data, name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if parsed != parsed or parsed.is_infinite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
    if parsed < Decimal(min_value) or parsed > Decimal(max_value):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be between %s and %s." % (name, min_value, max_value))
    from services.calc import round_half_up
    return round_half_up(parsed, 2)


def req_bool(data, name):
    _present(data, name)
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_enum(data, name, allowed):
    _present(data, name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_instant(data, name):
    _present(data, name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    try:
        return clock.canonical(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)


def req_state_codes(data, name):
    _present(data, name)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    if len(value) < 1 or len(value) > 10:
        fail("ERR_INVALID_REQUEST", "Field '%s' must hold 1 to 10 entries." % name)
    for entry in value:
        if not isinstance(entry, str) or not TWO_UPPER.match(entry):
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' entries must be exactly two uppercase letters." % name)
    if len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must not repeat a state code." % name)
    return list(value)
