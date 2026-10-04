"""Time, money and validation helpers.

Time format: PRD 2.4 -- ISO 8601 UTC with three fractional digits for
`created_at` / `updated_at`; PRD 2.8 -- volumes and shares round half up to
2dp, durability to 6dp, money is integer cents floored per term.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

from errors import APIError, ERR_INVALID_REQUEST

# PRD 2.5: every process starts here; the wall clock is never consulted.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})"
                    r"(?:\.(\d+))?([Zz]|[+-]\d{2}:?\d{2})?$")


def parse_instant(value, field="timestamp"):
    """Parse an ISO-8601 instant into an aware UTC datetime."""
    if value is None:
        raise APIError(ERR_INVALID_REQUEST, "%s is required" % field)
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise APIError(ERR_INVALID_REQUEST, "%s must be an ISO 8601 string" % field)
        m = _TS_RE.match(value.strip())
        if not m:
            raise APIError(ERR_INVALID_REQUEST, "%s is not a valid ISO 8601 instant" % field)
        year, month, day, hh, mm, ss = (int(m.group(i)) for i in range(1, 7))
        frac = m.group(7) or ""
        micro = int((frac + "000000")[:6])
        offset = m.group(8)
        try:
            dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone.utc)
        except ValueError:
            raise APIError(ERR_INVALID_REQUEST, "%s is not a valid calendar instant" % field)
        if offset and offset.upper() != "Z":
            sign = 1 if offset[0] == "+" else -1
            body = offset[1:].replace(":", "")
            dt = dt - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (dt.astimezone(timezone.utc).microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def yyyymm(dt):
    return dt.year * 100 + dt.month


# --- numeric discipline -----------------------------------------------------

GB_BYTES = 1073741824.0                      # PRD 2.8

HUNDRED = Decimal("100")
TWO = Decimal("0.01")
SIX = Decimal("0.000001")


def D(value):
    """Coerce to Decimal without binary-float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def money(value):
    """Integer cents, rounding half up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_floor(value):
    """Integer cents, floored -- PRD 2.8 floors each charge term."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def money_ceil(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def q2(value):
    """Two decimal places, round half up -- PRD 2.8."""
    return float(D(value).quantize(TWO, rounding=ROUND_HALF_UP))


def q6(value):
    """Six decimal places, round half up -- PRD 2.7."""
    return float(D(value).quantize(SIX, rounding=ROUND_HALF_UP))


def f2(value):
    """Two decimal places, round half up, floored (set storage_gb)."""
    return float(D(value).quantize(TWO, rounding=ROUND_FLOOR))


def dec2(value):
    return D(value).quantize(TWO, rounding=ROUND_HALF_UP)


def comb(n, k):
    if k < 0 or k > n:
        return 0
    return math.comb(n, k)


# --- request shape ----------------------------------------------------------

_MISSING = object()


def body_field(body, name, required=False, default=None, allow_null=False):
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, "request body must be a JSON object")
    if name not in body:
        if required:
            raise APIError(ERR_INVALID_REQUEST, "%s is required" % name)
        return default
    value = body[name]
    if value is None:
        if allow_null:
            return None
        if required:
            raise APIError(ERR_INVALID_REQUEST, "%s must not be null" % name)
        return default
    return value


def req_str(body, name, required=True, default=None):
    value = body_field(body, name, required=required, default=default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise APIError(ERR_INVALID_REQUEST, "%s must be a string" % name)
    return value


def req_enum(body, name, allowed, required=True, default=None, allow_absent_null=False):
    value = body_field(body, name, required=required, default=default,
                       allow_null=allow_absent_null)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise APIError(ERR_INVALID_REQUEST,
                       "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def req_num(body, name, required=True, default=None, allow_null=False):
    value = body_field(body, name, required=required, default=default, allow_null=allow_null)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise APIError(ERR_INVALID_REQUEST, "%s must be a number" % name)
    return value


def req_int(body, name, required=True, default=None, allow_null=False):
    value = body_field(body, name, required=required, default=default, allow_null=allow_null)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        raise APIError(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    return value


def req_bool(body, name, required=False, default=None):
    value = body_field(body, name, required=required, default=default)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise APIError(ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return value


# --- query shape ------------------------------------------------------------

def q_int(args, name, default=None, allow_null=False):
    if name not in args:
        return default
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, "%s must be an integer" % name)


def q_bool(args, name, default=None):
    if name not in args:
        return default
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in ("true", "1", "yes"):
        return True
    if raw.lower() in ("false", "0", "no"):
        return False
    raise APIError(ERR_INVALID_REQUEST, "%s must be a boolean" % name)


def pagination(args):
    """PRD 2.3: limit defaults to 10, min 1, max 100, offset defaults to 0."""
    limit = q_int(args, "limit", 10)
    offset = q_int(args, "offset", 0)
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise APIError(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, "offset must not be negative")
    return limit, offset