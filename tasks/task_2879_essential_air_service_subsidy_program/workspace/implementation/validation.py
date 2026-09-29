"""Request-shape validation (PRD section 2.6 rung 3).

Bodies are parsed with ``parse_float=Decimal`` so the literal decimal width a
client sent is preserved exactly and can be checked against the declared width.
"""

import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

import errors
from db import dec_places, parse_iso

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

_MISSING = object()


def bad(message):
    errors.fail(errors.ERR_INVALID_REQUEST, message)


def body(required=True):
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            return {}
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def present(data, key):
    return key in data and data[key] is not None


def _fetch(data, key, required):
    if not isinstance(data, dict) or key not in data or data[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _MISSING
    return data[key]


# ---------------------------------------------------------------------------
def str_field(data, key, required=True, min_len=1, max_len=None, pattern=None,
              default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' may be at most %d characters." % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("Field '%s' does not match its required form." % key)
    return value


def id_field(data, key, required=True):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty identifier string." % key)
    return value


def int_field(data, key, required=True, minimum=None, maximum=None,
              allowed=None, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' may not be below %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' may not exceed %s." % (key, maximum))
    if allowed is not None and value not in allowed:
        bad("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def num_field(data, key, required=True, places=2, minimum=None, maximum=None,
              exclusive_minimum=None, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % key)
    if dec_places(value) > places:
        bad("Field '%s' may carry at most %d decimal places." % (key, places))
    value = Decimal(value) if not isinstance(value, Decimal) else value
    if minimum is not None and value < Decimal(str(minimum)):
        bad("Field '%s' may not be below %s." % (key, minimum))
    if exclusive_minimum is not None and value <= Decimal(str(exclusive_minimum)):
        bad("Field '%s' must be greater than %s." % (key, exclusive_minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        bad("Field '%s' may not exceed %s." % (key, maximum))
    return value


def bool_field(data, key, required=True, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def enum_field(data, key, allowed, required=True, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def month_field(data, key, required=True, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not MONTH_RE.match(value):
        bad("Field '%s' must be a YYYY-MM month string." % key)
    return value


def datetime_field(data, key, required=True, default=None):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    parsed = parse_iso(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return parsed


def parse_stamp(value):
    """Re-parse a timestamp the server itself stored; always well formed."""
    return parse_iso(value)


def list_field(data, key, required=True):
    value = _fetch(data, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    return value
