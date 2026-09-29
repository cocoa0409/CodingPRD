"""Request-shape validation (ladder step 4 of PRD section 2.8).

Every violation in this module answers ERR_INVALID_REQUEST (400).
"""

import datetime as _dt
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import request

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]00:00|[+-]0000)$"
)

_MISSING = object()


def body():
    """Parse the JSON body, keeping decimal literals exact."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------

def _present(data, name, required):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return _MISSING
    return data[name]


def string_field(data, name, required=True, allow_blank=False, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-blank." % name)
    return value


def enum_field(data, name, allowed, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def bool_field(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def int_field(data, name, required=True, minimum=None, maximum=None,
              exclusive_min=None, default=None, allowed=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        number = value
    elif isinstance(value, Decimal) and value == value.to_integral_value():
        number = int(value)
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    _range_check(name, Decimal(number), minimum, maximum, exclusive_min)
    if allowed is not None and number not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' carries an undeclared value." % name)
    return number


def decimal_field(data, name, required=True, scale=None, minimum=None,
                  maximum=None, exclusive_min=None, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if not number.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
    if scale is not None:
        exponent = number.normalize().as_tuple().exponent
        if exponent < -scale:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' carries more than %d decimal places." % (name, scale))
    _range_check(name, number, minimum, maximum, exclusive_min)
    if scale is not None:
        # Store at the field's declared scale so reads echo the declared
        # precision (PRD section 2.6).
        number = number.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    return number


def _range_check(name, number, minimum, maximum, exclusive_min):
    if minimum is not None and number < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its declared minimum." % name)
    if exclusive_min is not None and number <= Decimal(str(exclusive_min)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be strictly greater than %s." % (name, exclusive_min))
    if maximum is not None and number > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its declared maximum." % name)


def date_field(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 calendar date." % name)
    try:
        return _dt.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a real calendar date." % name)


def instant_field(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC instant." % name)
    match = _INSTANT_RE.match(value)
    if not match:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC instant." % name)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = match.group(7) or ""
    micro = 0
    if fraction:
        digits = (fraction[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return _dt.datetime(year, month, day, hour, minute, second, micro,
                            tzinfo=_dt.timezone.utc)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a real instant." % name)


def string_array_field(data, name, required=True, default=None, distinct=False,
                       allowed=None, non_empty=False):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for entry in value:
        if not isinstance(entry, str):
            fail("ERR_INVALID_REQUEST", "Every entry of '%s' must be a string." % name)
        if allowed is not None and entry not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' carries an undeclared value." % name)
    if distinct and len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "Entries of '%s' must be distinct." % name)
    if non_empty and not value:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % name)
    return value


def object_array_field(data, name, required=True, default=None):
    value = _present(data, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for entry in value:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Every entry of '%s' must be an object." % name)
    return value


# ---------------------------------------------------------------------------
# Pagination and filters (PRD section 2.3)
# ---------------------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must sit between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be zero or greater.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def filters(*names):
    out = {}
    for name in names:
        value = request.args.get(name)
        if value is not None:
            out[name] = value
    return out
