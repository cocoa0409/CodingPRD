"""Payload-shape validation, date/number parsing and rounding (PRD 2.5, 2.8 tier 5)."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError

Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
ZERO = Decimal("0")


def r2(value):
    return Decimal(value).quantize(Q2, rounding=ROUND_HALF_UP)


def r4(value):
    return Decimal(value).quantize(Q4, rounding=ROUND_HALF_UP)


def money(value):
    """Normalise a stored monetary amount to two decimal places."""
    return r2(value)


# --- dates and instants -----------------------------------------------------
def parse_date(text, err="ERR_VALIDATION", field="date"):
    if not isinstance(text, str) or len(text) != 10:
        raise ApiError(err, "%s must be a YYYY-MM-DD calendar date." % field)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(err, "%s must be a YYYY-MM-DD calendar date." % field)


def d(text):
    """Parse a stored YYYY-MM-DD string (already validated)."""
    if text is None:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def iso_date(value):
    return value.isoformat() if isinstance(value, date) else value


def add_days(text, days):
    return (d(text) + timedelta(days=days)).isoformat()


def days_between(later, earlier):
    return (d(later) - d(earlier)).days


def add_years_minus_day(text, years):
    start = d(text)
    try:
        shifted = start.replace(year=start.year + years)
    except ValueError:  # 29 February
        shifted = start.replace(year=start.year + years, day=28)
    return (shifted - timedelta(days=1)).isoformat()


def parse_instant(text, err="ERR_VALIDATION", field="timestamp"):
    if not isinstance(text, str) or not text:
        raise ApiError(err, "%s must be an ISO 8601 UTC instant." % field)
    raw = text.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(err, "%s must be an ISO 8601 UTC instant." % field)
    if parsed.tzinfo is not None:
        parsed = (parsed - parsed.utcoffset()).replace(tzinfo=None)
    return parsed


# --- payload access ---------------------------------------------------------
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return payload


def _require(payload, key, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        raise ApiError(err, "%s is required." % key)
    return payload[key]


def to_decimal(value, key, err="ERR_VALIDATION"):
    if isinstance(value, bool):
        raise ApiError(err, "%s must be a number." % key)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return Decimal(text)
            except InvalidOperation:
                pass
    raise ApiError(err, "%s must be a number." % key)


def _check_scale(value, key, places, err="ERR_VALIDATION"):
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > places:
        raise ApiError(
            err, "%s may carry at most %d decimal places." % (key, places)
        )
    return value


def v_str(payload, key, required=True, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value.strip() == "":
        raise ApiError(err, "%s must be a non-empty string." % key)
    return value


def v_enum(payload, key, allowed, required=True, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(err, "%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def v_money(
    payload,
    key,
    required=True,
    default=None,
    minimum=ZERO,
    exclusive_minimum=False,
    maximum=None,
    err="ERR_VALIDATION",
):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = to_decimal(payload[key], key, err)
    _check_scale(value, key, 2, err)
    if minimum is not None:
        if exclusive_minimum and value <= minimum:
            raise ApiError(err, "%s must be greater than %s." % (key, minimum))
        if not exclusive_minimum and value < minimum:
            raise ApiError(err, "%s may not be below %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(err, "%s may not exceed %s." % (key, maximum))
    return r2(value)


def v_decimal(
    payload,
    key,
    places=2,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    err="ERR_VALIDATION",
):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = to_decimal(payload[key], key, err)
    _check_scale(value, key, places, err)
    if minimum is not None and value < minimum:
        raise ApiError(err, "%s may not be below %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(err, "%s may not exceed %s." % (key, maximum))
    return value


def v_int(
    payload, key, required=True, default=None, minimum=None, maximum=None,
    err="ERR_VALIDATION",
):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = payload[key]
    if isinstance(value, bool):
        raise ApiError(err, "%s must be an integer." % key)
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float) and float(value).is_integer():
        parsed = int(value)
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        parsed = int(value.strip())
    else:
        raise ApiError(err, "%s must be an integer." % key)
    if minimum is not None and parsed < minimum:
        raise ApiError(err, "%s may not be below %d." % (key, minimum))
    if maximum is not None and parsed > maximum:
        raise ApiError(err, "%s may not exceed %d." % (key, maximum))
    return parsed


def v_bool(payload, key, required=False, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ApiError(err, "%s must be a boolean." % key)
    return value


def v_date(payload, key, required=True, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    parse_date(payload[key], err, key)
    return payload[key]


def v_instant(payload, key, required=True, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return default
    parse_instant(payload[key], err, key)
    return payload[key]


def v_id(payload, key, required=True, default=None, err="ERR_VALIDATION"):
    return v_str(payload, key, required, default, err)


def v_enum_list(payload, key, allowed, required=True, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return list(default) if default is not None else None
    value = payload[key]
    if not isinstance(value, list) or (required and len(value) == 0):
        raise ApiError(err, "%s must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise ApiError(err, "%s entries must be drawn from %s." % (key, ", ".join(allowed)))
    return list(value)


def v_str_list(payload, key, required=False, default=None, err="ERR_VALIDATION"):
    if key not in payload or payload[key] is None:
        if required:
            raise ApiError(err, "%s is required." % key)
        return list(default) if default is not None else None
    value = payload[key]
    if not isinstance(value, list):
        raise ApiError(err, "%s must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            raise ApiError(err, "%s entries must be strings." % key)
    return list(value)
