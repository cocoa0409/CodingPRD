"""Numeric precision, temporal helpers and request payload validation."""
import calendar
import re
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from datetime import datetime, timedelta, timezone

from errors import ApiError, invalid

CENTS = Decimal("0.01")
SIX = Decimal("0.000001")
ZERO = Decimal("0")

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# --------------------------------------------------------------------------
# Decimal helpers - money is 2 dp round-half-up, factors are 6 dp round-half-up
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise invalid("expected a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise invalid("expected a number")
    if value is None:
        return ZERO
    raise invalid("expected a number")


def money(value):
    return D(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def factor(value):
    return D(value).quantize(SIX, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Temporal helpers - ISO 8601 UTC with exactly three fractional digits
# --------------------------------------------------------------------------
def fmt_dt(value):
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value.strip(), pattern)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight_utc(year, month, day):
    return datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_months(dt, months):
    months = int(months)
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def days_between(later, earlier):
    """Whole days from `earlier` to `later`, discarding any fractional day."""
    delta = later - earlier
    seconds = delta.total_seconds()
    return int(seconds // 86400)


# --------------------------------------------------------------------------
# Payload validation primitives - every failure is ERR_INVALID_REQUEST (400)
# --------------------------------------------------------------------------
_MISSING = object()


def _present(body, key):
    value = body.get(key, _MISSING)
    return value


def req_str(body, key, allow_empty=True):
    value = _present(body, key)
    if value is _MISSING or value is None:
        raise invalid("'%s' is required" % key)
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % key)
    if not allow_empty and not value.strip():
        raise invalid("'%s' must not be empty" % key)
    return value


def opt_str(body, key, default=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        raise invalid("'%s' must be a string" % key)
    return value


def req_state_code(body, key):
    value = req_str(body, key)
    if not STATE_CODE_RE.match(value):
        raise invalid("'%s' must be exactly two uppercase letters" % key)
    return value


def opt_state_code(body, key, default=None):
    value = opt_str(body, key, None)
    if value is None:
        return default
    if not STATE_CODE_RE.match(value):
        raise invalid("'%s' must be exactly two uppercase letters" % key)
    return value


def _check_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("'%s' must be an integer" % key)
    return value


def req_int(body, key, minv=None, maxv=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        raise invalid("'%s' is required" % key)
    value = _check_int(key, value)
    _range_int(key, value, minv, maxv)
    return value


def opt_int(body, key, default=None, minv=None, maxv=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        return default
    value = _check_int(key, value)
    _range_int(key, value, minv, maxv)
    return value


def _range_int(key, value, minv, maxv):
    if minv is not None and value < minv:
        raise invalid("'%s' must be >= %s" % (key, minv))
    if maxv is not None and value > maxv:
        raise invalid("'%s' must be <= %s" % (key, maxv))


def _as_number(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("'%s' must be a number" % key)
    return D(value)


def req_num(body, key, minv=None, maxv=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        raise invalid("'%s' is required" % key)
    number = _as_number(key, value)
    _range_num(key, number, minv, maxv)
    return number


def opt_num(body, key, default=None, minv=None, maxv=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        return default
    number = _as_number(key, value)
    _range_num(key, number, minv, maxv)
    return number


def _range_num(key, value, minv, maxv):
    if minv is not None and value < D(minv):
        raise invalid("'%s' is below its permitted minimum" % key)
    if maxv is not None and value > D(maxv):
        raise invalid("'%s' is above its permitted maximum" % key)


def req_bool(body, key):
    value = _present(body, key)
    if value is _MISSING or value is None:
        raise invalid("'%s' is required" % key)
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % key)
    return value


def opt_bool(body, key, default=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % key)
    return value


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        raise invalid("'%s' must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, key, allowed, default=None):
    value = opt_str(body, key, None)
    if value is None:
        return default
    if value not in allowed:
        raise invalid("'%s' must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def req_dt(body, key):
    value = _present(body, key)
    if value is _MISSING or value is None:
        raise invalid("'%s' is required" % key)
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 timestamp" % key)
    return parsed


def opt_dt(body, key, default=None):
    value = _present(body, key)
    if value is _MISSING or value is None:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 timestamp" % key)
    return parsed


def req_id(body, key):
    """A foreign key supplied in the body: must be present and a string."""
    value = _present(body, key)
    if value is _MISSING or value is None:
        return None
    if not isinstance(value, str):
        return None
    return value
