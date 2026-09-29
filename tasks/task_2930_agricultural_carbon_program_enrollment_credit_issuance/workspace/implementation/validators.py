"""Request-shape validation (validation rung 5: ERR_INVALID_REQUEST)."""

import datetime
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_SENTINEL = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Parse the request body, tolerating an absent body as ``{}``."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def supplied(body, key):
    return key in body and body[key] is not None


def _fetch(body, key, required):
    if key not in body or body[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _SENTINEL
    return body[key]


def v_str(body, key, required=True, allow_empty=False, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must not be empty." % key)
    return value


def v_enum(body, key, allowed, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def v_bool(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def v_int(body, key, required=True, minimum=None, maximum=None, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' may not exceed %s." % (key, maximum))
    return value


def v_crop_year(body, key, required=True, default=None):
    return v_int(body, key, required=required, minimum=2000, maximum=2100, default=default)


def v_dec(body, key, scale, required=True, minimum=None, maximum=None,
          exclusive_min=False, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, str):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if not dec.is_finite():
        bad("Field '%s' must be a finite number." % key)
    exponent = dec.as_tuple().exponent
    if exponent < -scale:
        normalised = dec.normalize()
        if normalised.as_tuple().exponent < -scale:
            bad("Field '%s' may carry at most %d decimal places." % (key, scale))
    if minimum is not None:
        if exclusive_min:
            if dec <= Decimal(str(minimum)):
                bad("Field '%s' must be greater than %s." % (key, minimum))
        elif dec < Decimal(str(minimum)):
            bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' may not exceed %s." % (key, maximum))
    return dec


def v_str_list(body, key, required=True, allowed=None, non_empty_members=True, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings." % key)
        if non_empty_members and item.strip() == "":
            bad("Field '%s' must not contain empty strings." % key)
        if allowed is not None and item not in allowed:
            bad("Field '%s' contains an unsupported value '%s'." % (key, item))
        out.append(item)
    return out


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?[Zz]$"
)


def v_date(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return default
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad("Field '%s' must be a calendar date formatted YYYY-MM-DD." % key)
    try:
        datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("Field '%s' must be a valid calendar date." % key)
    return value


def parse_date_prefix(value):
    """Read the calendar date out of a date or full-instant string."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def v_instant(body, key, required=True):
    value = _fetch(body, key, required)
    if value is _SENTINEL:
        return None, None
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % key)
    match = _INSTANT_RE.match(value)
    if not match:
        bad("Field '%s' must be an ISO 8601 UTC instant ending in Z." % key)
    frac = match.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        dt = datetime.datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
            micro % 1000000,
        )
    except ValueError:
        bad("Field '%s' must be a valid ISO 8601 UTC instant." % key)
    return value, dt
