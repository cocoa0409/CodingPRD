"""Request-shape validation (PRD 2.8 rung 3) -> ERR_INVALID_REQUEST."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
SCHOOL_YEAR_RE = re.compile(r"^\d{4}-\d{4}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def _require(data, key):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    return data[key]


def get_str(data, key, required=True, default=None, pattern=None, allow_empty=False):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value == "":
        bad("Field '%s' must not be empty." % key)
    if pattern is not None and not pattern.match(value):
        bad("Field '%s' is malformed." % key)
    return value


def get_int(data, key, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum." % key)
    return value


def get_number(data, key, required=True, default=None, minimum=None, maximum=None,
               exclusive_minimum=None, exclusive_maximum=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum." % key)
    if exclusive_minimum is not None and not value > exclusive_minimum:
        bad("Field '%s' must be greater than %s." % (key, exclusive_minimum))
    if exclusive_maximum is not None and not value < exclusive_maximum:
        bad("Field '%s' must be less than %s." % (key, exclusive_maximum))
    return value


def get_bool(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def get_enum(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' is not one of the permitted values." % key)
    return value


def get_str_array(data, key, required=True, allowed=None, pattern=None, non_empty=True):
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    if non_empty and len(value) == 0:
        bad("Field '%s' must not be empty." % key)
    for element in value:
        if not isinstance(element, str):
            bad("Every element of '%s' must be a string." % key)
        if allowed is not None and element not in allowed:
            bad("Element '%s' of '%s' is not permitted." % (element, key))
        if pattern is not None and not pattern.match(element):
            bad("Element '%s' of '%s' is malformed." % (element, key))
    return list(value)


def parse_date_string(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("Field '%s' must be an ISO-8601 calendar date." % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("Field '%s' must be an ISO-8601 calendar date." % key)


def get_date(data, key, required=True, default=None):
    """Returns (raw string, datetime.date)."""
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return default, None
    raw = data[key]
    return raw, parse_date_string(raw, key)


def parse_instant_string(value, key):
    """Accept an ISO-8601 UTC instant; a bare calendar date means midnight UTC."""
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO-8601 UTC instant." % key)
    if DATE_RE.match(value):
        day = parse_date_string(value, key)
        return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    if not INSTANT_RE.match(value):
        bad("Field '%s' must be an ISO-8601 UTC instant ending in Z." % key)
    head = value[:-1]
    fraction = 0
    if "." in head:
        head, frac = head.split(".", 1)
        fraction = int((frac + "000000")[:6])
    try:
        parsed = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        bad("Field '%s' must be an ISO-8601 UTC instant." % key)
    return parsed.replace(microsecond=fraction, tzinfo=timezone.utc)


def get_instant(data, key, required=True):
    """Returns (raw string, aware datetime)."""
    if not _present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None, None
    raw = data[key]
    return raw, parse_instant_string(raw, key)
