"""Request-shape validation helpers (validation ladder rung 4).

Every failure here is ERR_INVALID_REQUEST (HTTP 422) unless a caller asks for a
different error id explicitly (the hour/credit grid of a delivered session).
"""

import calendar
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import ApiError, invalid

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

MISSING = object()


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------

def read_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body is not valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object")
    return payload


def present(body, key):
    return key in body and body[key] is not None


# --------------------------------------------------------------------------
# scalars
# --------------------------------------------------------------------------

def get_string(body, key, required=False, min_len=1, max_len=None, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % key)
    if len(value) < min_len:
        raise invalid("'%s' must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("'%s' must be at most %d characters" % (key, max_len))
    return value


def get_id(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not value:
        raise invalid("'%s' must be a non-empty string identifier" % key)
    return value


def get_state_code(body, key, required=False, default=None):
    value = get_string(body, key, required=required, min_len=1, max_len=None, default=MISSING)
    if value is MISSING:
        return default
    if not _STATE_RE.match(value):
        raise invalid("'%s' must be exactly two uppercase letters" % key)
    return value


def get_enum(body, key, members, required=False, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in members:
        raise invalid("'%s' must be one of %s" % (key, ", ".join(sorted(members))))
    return value


def get_bool(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % key)
    return value


def get_int(body, key, required=False, minimum=None, maximum=None, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool):
        raise invalid("'%s' must be an integer" % key)
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if float(value).is_integer():
            number = int(value)
        else:
            raise invalid("'%s' must be a whole number" % key)
    elif isinstance(value, str):
        try:
            number = int(value.strip())
        except Exception:
            raise invalid("'%s' must be an integer" % key)
    else:
        raise invalid("'%s' must be an integer" % key)
    if minimum is not None and number < minimum:
        raise invalid("'%s' must be >= %d" % (key, minimum))
    if maximum is not None and number > maximum:
        raise invalid("'%s' must be <= %d" % (key, maximum))
    return number


def get_decimal(body, key, required=False, minimum=None, maximum=None, default=None,
                exclusive_minimum=None, error_id=None):
    def fail(message):
        if error_id:
            raise ApiError(error_id, message)
        raise invalid(message)

    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool):
        raise invalid("'%s' must be a number" % key)
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, float):
        number = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            number = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise invalid("'%s' must be a number" % key)
    else:
        raise invalid("'%s' must be a number" % key)
    if number != number or number.is_infinite():  # NaN / inf
        raise invalid("'%s' must be a finite number" % key)
    if exclusive_minimum is not None and number <= exclusive_minimum:
        fail("'%s' must be greater than %s" % (key, exclusive_minimum))
    if minimum is not None and number < minimum:
        fail("'%s' must be >= %s" % (key, minimum))
    if maximum is not None and number > maximum:
        fail("'%s' must be <= %s" % (key, maximum))
    return number


def get_date(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise invalid("'%s' must be an ISO 8601 date of the form YYYY-MM-DD" % key)
    try:
        year, month, day = [int(part) for part in value.split("-")]
        return date(year, month, day)
    except Exception:
        raise invalid("'%s' must be a valid calendar date" % key)


def get_string_list(body, key, members=None, default=None):
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if not isinstance(value, list):
        raise invalid("'%s' must be an array" % key)
    for item in value:
        if not isinstance(item, str):
            raise invalid("'%s' must be an array of strings" % key)
        if members is not None and item not in members:
            raise invalid("'%s' contains an unsupported value" % key)
    return value


def get_instant(body, key, required=False):
    """Full ISO 8601 UTC instant used by the logical clock endpoint."""
    from datetime import datetime, timedelta, timezone

    if not present(body, key):
        if required:
            raise invalid("'%s' is required" % key)
        return None
    value = body[key]
    if not isinstance(value, str):
        raise invalid("'%s' must be an ISO 8601 UTC instant string" % key)
    match = _INSTANT_RE.match(value.strip())
    if not match:
        raise invalid("'%s' must be a full ISO 8601 UTC instant" % key)
    year, month, day, hour, minute = [int(match.group(i)) for i in range(1, 6)]
    second = int(match.group(6) or 0)
    fraction = match.group(7) or ""
    micro = int((fraction + "000000")[:6]) if fraction else 0
    offset = match.group(8)
    try:
        moment = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except Exception:
        raise invalid("'%s' must be a valid instant" % key)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        moment = moment - sign * delta
    return moment


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

def pagination_params():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            raise invalid("'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise invalid("'limit' must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            raise invalid("'offset' must be an integer")
        if offset < 0:
            raise invalid("'offset' must be >= 0")
    return limit, offset


def query_string(key):
    value = request.args.get(key)
    if value is None:
        return None
    return value


def query_enum(key, members):
    value = request.args.get(key)
    if value is None:
        return None
    if value not in members:
        raise invalid("'%s' must be one of %s" % (key, ", ".join(sorted(members))))
    return value


def query_bool(key):
    value = request.args.get(key)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("'%s' must be true or false" % key)


# --------------------------------------------------------------------------
# numeric / date arithmetic
# --------------------------------------------------------------------------

TWO_PLACES = Decimal("0.01")


def money(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_half_up(value, places=2):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def add_months(anchor, months):
    total = anchor.month - 1 + months
    year = anchor.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last_day))


def add_years(anchor, years):
    return add_months(anchor, 12 * years)


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_iso_date(value):
    if value is None:
        return None
    if isinstance(value, date):
        return value
    year, month, day = [int(part) for part in value.split("-")]
    return date(year, month, day)


def is_quarter_multiple(value):
    return (Decimal(value) % Decimal("0.25")) == 0
