"""Request-shape validation — rung 3 of the thirty-four-rung ladder (PRD §2.7).

Every violation here raises ERR_INVALID_REQUEST (HTTP 422).
"""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ERR_INVALID_REQUEST, ApiError

_MISSING = object()

# PRD §2.5: a submitted datetime "must be a valid ISO 8601 UTC instant", spelled
# the way the PRD spells every instant it shows (`2026-08-01T09:15:00.000Z`): the
# `T` separator, whole seconds, optional fractional digits and the `Z` UTC
# designator. PRD §3.5 forecloses the permissive reading outright — the peak band
# reads "the UTC hour of the submitted instant and never a local-time
# conversion" — so a naive or offset-bearing spelling is not a UTC instant and is
# a rung-3 shape violation.
INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def bad(message):
    raise ApiError(ERR_INVALID_REQUEST, message)


def json_body():
    """Parsed JSON object body; a missing or unparseable body reads as empty."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(body, key):
    return key in body and body[key] is not None


# --------------------------------------------------------------------------
# datetime / date parsing (PRD §2.5)
# --------------------------------------------------------------------------

def parse_instant(value, key="value"):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    match = INSTANT_RE.match(value.strip())
    if not match:
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    frac = match.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return naive.replace(tzinfo=timezone.utc)


def parse_date(value, key="value"):
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    match = DATE_RE.match(value.strip())
    if not match:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    from datetime import date as _date

    try:
        return _date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)


# --------------------------------------------------------------------------
# scalar field readers
# --------------------------------------------------------------------------

def _raw(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _MISSING if default is _MISSING else default
    return body[key]


def field_str(body, key, required=True, default=_MISSING, min_len=1, max_len=None,
              pattern=None, upper=False):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("Field '%s' has an invalid format." % key)
    if upper and value != value.upper():
        bad("Field '%s' must be uppercase." % key)
    return value


def field_int(body, key, required=True, default=_MISSING, minimum=None, maximum=None,
              multiple_of=None):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (key, maximum))
    if multiple_of is not None and value % multiple_of != 0:
        bad("Field '%s' must be a multiple of %d." % (key, multiple_of))
    return value


def field_decimal_1dp(body, key, required=True, default=_MISSING, minimum=None,
                      maximum=None, exclusive_minimum=None):
    """A number carrying at most one decimal place (PRD §2.6)."""
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        bad("Field '%s' must be a number." % key)
    if dec.as_tuple().exponent < -1:
        bad("Field '%s' carries more than one decimal place." % key)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (key, minimum))
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        bad("Field '%s' must be greater than %s." % (key, exclusive_minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (key, maximum))
    return dec.quantize(Decimal("0.1")) if dec.as_tuple().exponent == -1 else dec


def field_bool(body, key, required=True, default=_MISSING):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def field_enum(body, key, choices, required=True, default=_MISSING):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(choices))))
    return value


def field_str_array(body, key, required=True, default=_MISSING, upper=False):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return list(value) if isinstance(value, list) else value
    if not isinstance(value, list):
        bad("Field '%s' must be an array of strings." % key)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings." % key)
        if upper and item != item.upper():
            bad("Field '%s' entries must be uppercase." % key)
    return list(value)


def field_instant(body, key, required=True, default=_MISSING):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    return parse_instant(value, key)


def field_date(body, key, required=True, default=_MISSING):
    value = _raw(body, key, required, default)
    if value is _MISSING:
        return None
    if key not in body or body[key] is None:
        return value
    return parse_date(value, key)


def field_id(body, key, required=True):
    value = _raw(body, key, required, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be a non-empty string identifier." % key)
    return value


# --------------------------------------------------------------------------
# query-string helpers
# --------------------------------------------------------------------------

def query_int(key, default=None, minimum=None, maximum=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        bad("Query parameter '%s' must be an integer." % key)
    value = int(raw.strip())
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be at most %s." % (key, maximum))
    return value


def query_enum(key, choices, default=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return default
    if raw not in choices:
        bad("Query parameter '%s' must be one of %s." % (key, ", ".join(sorted(choices))))
    return raw


def query_str(key, default=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return default
    return raw


def query_instant(key, required=False, error_id=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        if required:
            if error_id:
                raise ApiError(error_id, "Query parameter '%s' is required." % key)
            bad("Query parameter '%s' is required." % key)
        return None
    return parse_instant(raw, key)


def query_date(key, default=None):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return default
    return parse_date(raw, key)


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = query_int("limit", default=10, minimum=1, maximum=100)
    offset = query_int("offset", default=0, minimum=0)
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
