"""Request-shape validation helpers (PRD section 2.9 rank 3) and date parsing."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Return the JSON object body, or {} when no body was sent at all."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def lenient_body():
    """Body access for the ownership pre-check; never raises."""
    parsed = request.get_json(silent=True, force=True)
    return parsed if isinstance(parsed, dict) else {}


# ------------------------------------------------------------------- primitives
def string_field(data, key, min_len=1, max_len=None, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("%s must be a string" % key)
    if len(value) < min_len:
        bad("%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (key, max_len))
    return value


def int_field(data, key, minimum=None, maximum=None, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("%s must be at least %d" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %d" % (key, maximum))
    return value


def bool_field(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % key)
    return value


def decimal_field(data, key, minimum, maximum, places, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s must be numeric" % key)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be numeric" % key)
    if not number.is_finite():
        bad("%s must be numeric" % key)
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        bad("%s supports at most %d decimal places" % (key, places))
    if number < Decimal(str(minimum)) or number > Decimal(str(maximum)):
        bad("%s must lie between %s and %s inclusive" % (key, minimum, maximum))
    quantum = Decimal(1).scaleb(-places)
    return number.quantize(quantum)


def enum_field(data, key, allowed, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def string_list_field(data, key, min_items, max_items, item_min, item_max,
                      required=True, default=None, unique=True):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, list):
        bad("%s must be an array of strings" % key)
    if len(value) < min_items:
        bad("%s must contain at least %d entries" % (key, min_items))
    if max_items is not None and len(value) > max_items:
        bad("%s must contain at most %d entries" % (key, max_items))
    for item in value:
        if not isinstance(item, str):
            bad("%s entries must be strings" % key)
        if len(item) < item_min:
            bad("%s entries must be non-empty" % key)
        if item_max is not None and len(item) > item_max:
            bad("%s entries must be at most %d characters" % (key, item_max))
    if unique and len(set(value)) != len(value):
        bad("%s entries must be unique" % key)
    return list(value)


# ------------------------------------------------------------ dates and instants
def parse_date(text, key):
    if not isinstance(text, str):
        bad("%s must be an ISO-8601 date" % key)
    candidate = text.strip()
    if len(candidate) != 10:
        bad("%s must be an ISO-8601 date (YYYY-MM-DD)" % key)
    try:
        return date.fromisoformat(candidate)
    except ValueError:
        bad("%s must be an ISO-8601 date (YYYY-MM-DD)" % key)


def date_field(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    return parse_date(data[key], key)


def parse_instant(text, key):
    if not isinstance(text, str):
        bad("%s must be an ISO-8601 UTC instant" % key)
    candidate = text.strip()
    if "T" not in candidate:
        bad("%s must be an ISO-8601 UTC instant" % key)
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        bad("%s must be an ISO-8601 UTC instant" % key)
    if parsed.tzinfo is not None:
        offset = parsed.utcoffset()
        parsed = (parsed - offset).replace(tzinfo=None) if offset else parsed.replace(tzinfo=None)
    return parsed


def instant_field(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            bad("%s is required" % key)
        return default
    return parse_instant(data[key], key)


def forbid(data, key, message):
    if key in data and data[key] is not None:
        bad(message)
