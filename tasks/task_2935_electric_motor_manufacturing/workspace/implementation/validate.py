"""Payload shape validation (PRD 2.11 priority "payload shape" band).

Every failure in this module is reported as ERR_INVALID_REQUEST (HTTP 400):
required fields present, correct types, enum values inside their declared sets,
numeric values inside their declared ranges and decimal widths, ISO 8601
instants with a Z suffix, calendar dates as YYYY-MM-DD, and every interval pair
satisfying end strictly after start.
"""

import datetime
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

MISSING = object()


def parse_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def present(body, key):
    return key in body and body[key] is not None


def _require(body, key):
    if not present(body, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    return body[key]


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def req_str(body, key, min_len=1, max_len=None):
    value = _require(body, key)
    return _check_str(key, value, min_len, max_len)


def opt_str(body, key, min_len=1, max_len=None, default=None):
    if not present(body, key):
        return default
    return _check_str(key, body[key], min_len, max_len)


def _check_str(key, value, min_len, max_len):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %d characters." % (key, max_len))
    return value


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------

def req_enum(body, key, allowed):
    value = _require(body, key)
    return _check_enum(key, value, allowed)


def opt_enum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    return _check_enum(key, body[key], allowed)


def _check_enum(key, value, allowed):
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------

def req_int(body, key, lo=None, hi=None):
    value = _require(body, key)
    return _check_int(key, value, lo, hi)


def opt_int(body, key, lo=None, hi=None, default=None):
    if not present(body, key):
        return default
    return _check_int(key, body[key], lo, hi)


def _check_int(key, value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (key, lo))
    if hi is not None and value > hi:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (key, hi))
    return value


# --------------------------------------------------------------------------
# decimals
# --------------------------------------------------------------------------

def req_num(body, key, lo=None, hi=None, places=None):
    value = _require(body, key)
    return _check_num(key, value, lo, hi, places)


def opt_num(body, key, lo=None, hi=None, places=None, default=None):
    if not present(body, key):
        return default
    return _check_num(key, body[key], lo, hi, places)


def _check_num(key, value, lo, hi, places):
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        try:
            value = Decimal(repr(value))
        except InvalidOperation:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if not value.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % key)
    if places is not None:
        exponent = value.normalize().as_tuple().exponent
        if exponent < -places:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must carry at most %d decimal places." % (key, places))
    if lo is not None and value < Decimal(str(lo)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (key, lo))
    if hi is not None and value > Decimal(str(hi)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at most %s." % (key, hi))
    return value


# --------------------------------------------------------------------------
# booleans, objects
# --------------------------------------------------------------------------

def opt_bool(body, key, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def opt_object(body, key, default=None):
    if not present(body, key):
        return {} if default is None else default
    value = body[key]
    if not isinstance(value, dict):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an object." % key)
    return value


# --------------------------------------------------------------------------
# instants and dates
# --------------------------------------------------------------------------

def req_instant(body, key):
    value = _require(body, key)
    return _check_instant(key, value)


def opt_instant(body, key, default=None):
    if not present(body, key):
        return default
    return _check_instant(key, body[key])


def _check_instant(key, value):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC instant." % key)
    match = _INSTANT_RE.match(value)
    if not match:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO 8601 UTC instant ending in Z." % key)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime.datetime(year, month, day, hour, minute, second, micro,
                                 tzinfo=datetime.timezone.utc)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid instant." % key)


def req_date(body, key):
    value = _require(body, key)
    return _check_date(key, value)


def _check_date(key, value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD calendar date." % key)
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid calendar date." % key)
    return value


def as_date(value):
    return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def interval(start, end, start_key, end_key):
    """PRD 2.11 — every interval pair must satisfy end strictly after start."""
    if not (end > start):
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be strictly after '%s'." % (end_key, start_key))
