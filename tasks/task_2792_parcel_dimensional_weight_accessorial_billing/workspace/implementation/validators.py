"""Request-schema validation (PRD 2.6, PRD 2.10 tier 3).

Every failure in here is ERR_INVALID_REQUEST (HTTP 400).
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_day, parse_instant

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    """Parse the JSON body; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def peek_str(body, key):
    """Return the value only when it is a usable string, else None.

    Used for existence resolution (PRD 2.10 tier 2), which runs before the
    schema tier and therefore cannot itself raise a schema error.
    """
    value = body.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def peek_str_list(body, key):
    value = body.get(key)
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v]


# --------------------------------------------------------------------------
# scalar field readers
# --------------------------------------------------------------------------

def req_string(body, key, min_len=None, max_len=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not value:
        bad("Field '%s' must not be empty." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def opt_string(body, key, default=None, min_len=None, max_len=None):
    if key not in body or body.get(key) is None:
        return default
    return req_string(body, key, min_len=min_len, max_len=max_len)


def req_int(body, key, minimum=None, maximum=None):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not is_int(value):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int(body, key, minimum=minimum, maximum=maximum)


def req_bool(body, key):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=False):
    if key not in body or body.get(key) is None:
        return default
    return req_bool(body, key)


def req_enum(body, key, members):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(members))))
    return value


def opt_enum(body, key, members, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, members)


def req_measure(body, key, maximum):
    """A physical measurement: > 0, <= maximum, at most one decimal place."""
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not is_number(value):
        bad("Field '%s' must be a number." % key)
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if decimal_value <= 0:
        bad("Field '%s' must be greater than 0." % key)
    if decimal_value > Decimal(maximum):
        bad("Field '%s' must be at most %s." % (key, maximum))
    if -decimal_value.as_tuple().exponent > 1:
        bad("Field '%s' must carry at most one decimal place." % key)
    return value


def req_date(body, key):
    value = req_string(body, key)
    if parse_day(value) is None:
        bad("Field '%s' must be a calendar date in YYYY-MM-DD form." % key)
    return value


def req_instant(body, key):
    value = req_string(body, key)
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 instant." % key)
    return value, parsed


def opt_str_list(body, key, default=None, members=None):
    if key not in body or body.get(key) is None:
        return list(default) if default is not None else []
    value = body.get(key)
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or not item:
            bad("Field '%s' must be an array of strings." % key)
        if members is not None and item not in members:
            bad("Field '%s' contains an unknown value '%s'." % (key, item))
    return list(value)


# --------------------------------------------------------------------------
# composite field readers
# --------------------------------------------------------------------------

def req_rate_table(body, key):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not isinstance(value, list) or not value:
        bad("Field '%s' must be a non-empty array of rate rows." % key)
    rows = []
    for raw in value:
        if not isinstance(raw, dict):
            bad("Each '%s' row must be an object." % key)
        for field in ("zone", "min_lbs", "max_lbs", "cents_per_lb"):
            if field not in raw or raw.get(field) is None:
                bad("Rate row field '%s' is required." % field)
            if not is_int(raw.get(field)):
                bad("Rate row field '%s' must be an integer." % field)
        if raw["min_lbs"] > raw["max_lbs"]:
            bad("Rate row min_lbs must not exceed max_lbs.")
        if raw["cents_per_lb"] < 0:
            bad("Rate row cents_per_lb must be at least 0.")
        rows.append({
            "zone": raw["zone"],
            "min_lbs": raw["min_lbs"],
            "max_lbs": raw["max_lbs"],
            "cents_per_lb": raw["cents_per_lb"],
        })
    return rows


def req_tier_table(body, key):
    value = body.get(key, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % key)
    if not isinstance(value, list):
        bad("Field '%s' must be an array of tier rows." % key)
    rows = []
    for raw in value:
        if not isinstance(raw, dict):
            bad("Each '%s' row must be an object." % key)
        for field in ("min_transportation_subtotal_cents", "discount_bps"):
            if field not in raw or raw.get(field) is None:
                bad("Tier row field '%s' is required." % field)
            if not is_int(raw.get(field)):
                bad("Tier row field '%s' must be an integer." % field)
            if raw.get(field) < 0:
                bad("Tier row field '%s' must be at least 0." % field)
        rows.append({
            "min_transportation_subtotal_cents": raw["min_transportation_subtotal_cents"],
            "discount_bps": raw["discount_bps"],
        })
    return rows


def opt_overrides(body, key):
    if key not in body or body.get(key) is None:
        return {}
    value = body.get(key)
    if not isinstance(value, dict):
        bad("Field '%s' must be an object mapping accessorial code to cents." % key)
    out = {}
    for code, amount in value.items():
        if not is_int(amount) or amount < 0:
            bad("Field '%s' values must be integer cents of at least 0." % key)
        out[code] = amount
    return out
