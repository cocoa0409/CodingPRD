"""Request-body well-formedness checks (validation rung 5, ERR_INVALID_REQUEST)."""
import re
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import D

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        bad("request body must be a JSON object")
    return raw


def present(b, key):
    return key in b and b[key] is not None


# ---- strings ----------------------------------------------------------
def _check_str(value, key, minl, maxl):
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if minl is not None and len(value) < minl:
        bad("%s must be at least %d characters" % (key, minl))
    if maxl is not None and len(value) > maxl:
        bad("%s must be at most %d characters" % (key, maxl))
    return value


def req_str(b, key, minl=1, maxl=None):
    if not present(b, key):
        bad("%s is required" % key)
    return _check_str(b[key], key, minl, maxl)


def opt_str(b, key, minl=1, maxl=None, default=None):
    if not present(b, key):
        return default
    return _check_str(b[key], key, minl, maxl)


# ---- integers --------------------------------------------------------
def _check_int(value, key, lo, hi, choices=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % key)
    if choices is not None and value not in choices:
        bad("%s must be one of %s" % (key, sorted(choices)))
    if lo is not None and value < lo:
        bad("%s must be at least %s" % (key, lo))
    if hi is not None and value > hi:
        bad("%s must be at most %s" % (key, hi))
    return value


def req_int(b, key, lo=None, hi=None, choices=None):
    if not present(b, key):
        bad("%s is required" % key)
    return _check_int(b[key], key, lo, hi, choices)


def opt_int(b, key, lo=None, hi=None, choices=None, default=None):
    if not present(b, key):
        return default
    return _check_int(b[key], key, lo, hi, choices)


# ---- numbers ---------------------------------------------------------
def _check_num(value, key, lo, hi, exclusive_lo, dp, step):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % key)
    try:
        dv = D(value)
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % key)
    if exclusive_lo is not None and dv <= D(exclusive_lo):
        bad("%s must be greater than %s" % (key, exclusive_lo))
    if lo is not None and dv < D(lo):
        bad("%s must be at least %s" % (key, lo))
    if hi is not None and dv > D(hi):
        bad("%s must be at most %s" % (key, hi))
    if dp is not None and -dv.as_tuple().exponent > dp:
        bad("%s must carry at most %d decimal places" % (key, dp))
    if step is not None:
        if (dv / D(step)) % 1 != 0:
            bad("%s must be a multiple of %s" % (key, step))
    return dv


def req_num(b, key, lo=None, hi=None, exclusive_lo=None, dp=None, step=None):
    if not present(b, key):
        bad("%s is required" % key)
    return _check_num(b[key], key, lo, hi, exclusive_lo, dp, step)


def opt_num(b, key, lo=None, hi=None, exclusive_lo=None, dp=None, step=None,
            default=None):
    if not present(b, key):
        return default
    return _check_num(b[key], key, lo, hi, exclusive_lo, dp, step)


# ---- booleans / enums ------------------------------------------------
def req_bool(b, key):
    if not present(b, key):
        bad("%s is required" % key)
    if not isinstance(b[key], bool):
        bad("%s must be a boolean" % key)
    return b[key]


def opt_bool(b, key, default=None):
    if not present(b, key):
        return default
    if not isinstance(b[key], bool):
        bad("%s must be a boolean" % key)
    return b[key]


def req_enum(b, key, allowed):
    value = req_str(b, key, 1, None)
    if value not in allowed:
        bad("%s must be one of %s" % (key, sorted(allowed)))
    return value


def opt_enum(b, key, allowed, default=None):
    if not present(b, key):
        return default
    value = _check_str(b[key], key, 1, None)
    if value not in allowed:
        bad("%s must be one of %s" % (key, sorted(allowed)))
    return value


# ---- dates / datetimes -----------------------------------------------
def _check_date(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("%s must be an ISO 8601 date (YYYY-MM-DD)" % key)
    try:
        date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("%s must be a valid calendar date" % key)
    return value


def req_date(b, key):
    if not present(b, key):
        bad("%s is required" % key)
    return _check_date(b[key], key)


def opt_date(b, key, default=None):
    if not present(b, key):
        return default
    return _check_date(b[key], key)


def parse_dt(value, key):
    if not isinstance(value, str):
        bad("%s must be an ISO 8601 UTC timestamp" % key)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        bad("%s must be an ISO 8601 UTC timestamp" % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, key):
    if not present(b, key):
        bad("%s is required" % key)
    return parse_dt(b[key], key)
