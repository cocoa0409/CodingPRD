"""Request-body shape validation (PRD 2.7 check 7 -> ERR_INVALID_REQUEST)."""
import re
from datetime import date

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
SCHOOL_YEAR_RE = re.compile(r"^\d{4}-\d{4}$")

WEEKDAY_NAMES = ("MON", "TUE", "WED", "THU", "FRI")
# Monday-anchored: date.weekday() returns 0 for Monday.
WEEKDAY_BY_INDEX = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def bad(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("The request body must be a JSON object.")
    return data


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not present(data, key):
        raise bad("%s is required." % key)
    value = data[key]
    if not isinstance(value, str):
        raise bad("%s must be a string." % key)
    if len(value) < min_len:
        raise bad("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("%s must be at most %d characters." % (key, max_len))
    return value


def opt_str(data, key, min_len=0, max_len=None, default=None):
    if not present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def req_int(data, key, low=None, high=None):
    if not present(data, key):
        raise bad("%s is required." % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("%s must be an integer." % key)
    if value < 0:
        raise bad("%s must not be negative." % key)
    if low is not None and value < low:
        raise bad("%s must be at least %d." % (key, low))
    if high is not None and value > high:
        raise bad("%s must be at most %d." % (key, high))
    return value


def opt_int(data, key, low=None, high=None, default=None):
    if not present(data, key):
        return default
    return req_int(data, key, low, high)


def req_bool(data, key, default=False):
    if not present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise bad("%s must be a boolean." % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key, 1, None)
    if value not in allowed:
        raise bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not present(data, key):
        return default
    return req_enum(data, key, allowed)


def parse_date_str(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise bad("%s must be an ISO 8601 date formatted YYYY-MM-DD." % key)
    try:
        parts = [int(p) for p in value.split("-")]
        return date(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        raise bad("%s must be a valid calendar date." % key)


def req_date(data, key):
    if not present(data, key):
        raise bad("%s is required." % key)
    parse_date_str(data[key], key)
    return data[key]


def opt_date(data, key, default=None):
    if not present(data, key):
        return default
    return req_date(data, key)


def req_time(data, key):
    if not present(data, key):
        raise bad("%s is required." % key)
    value = data[key]
    if not isinstance(value, str) or not TIME_RE.match(value):
        raise bad("%s must be a 24-hour HH:MM time." % key)
    return value


def req_school_year(data, key):
    value = req_str(data, key, 1, 9)
    if not SCHOOL_YEAR_RE.match(value):
        raise bad("%s must be formatted YYYY-YYYY." % key)
    return value


def minutes_of(hhmm):
    return int(hhmm[0:2]) * 60 + int(hhmm[3:5])


def d(value):
    """Parse a stored YYYY-MM-DD string into a date."""
    parts = [int(p) for p in value.split("-")]
    return date(parts[0], parts[1], parts[2])
