"""Datetime, decimal, request-parsing, and field-validation helpers."""
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import raise_err

CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Logical-clock / input-echo timestamp: fractional part only when present."""
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_wall(dt):
    """created_at/updated_at/api_request_timestamp: always three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def D(value):
    return Decimal(str(value))


def round2_dec(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def round4_dec(d):
    return d.quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def num(value):
    """Decimal -> int when integral, else float. Other types pass through."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def decimal_places_ok(v, max_places=2):
    try:
        return -D(v).as_tuple().exponent <= max_places
    except Exception:
        return False


# ---------- request body helpers ----------

def get_body():
    from flask import request
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def req(body, name):
    if name not in body or body[name] is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: %s." % name)
    return body[name]


def as_str(v, name):
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    return v


def as_number(v, name):
    if not is_number(v):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a number." % name)
    return v


def as_int(v, name):
    if not is_int(v):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return v


def as_datetime(v, name):
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string." % name)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string." % name)


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise_err(
            "ERR_INVALID_REQUEST",
            "Field %s must be one of: %s." % (name, ", ".join(allowed)),
        )
    return v


def parse_month(v, name):
    m = _MONTH_RE.match(v) if isinstance(v, str) else None
    if not m:
        raise_err("ERR_INVALID_REQUEST", "Field %s must be in YYYY-MM format." % name)
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise_err("ERR_INVALID_REQUEST", "Field %s must be in YYYY-MM format." % name)
    return year, month


def month_start_of(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(year, month):
    if month == 12:
        return datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(year, month + 1, 1, tzinfo=timezone.utc)


def parse_pagination():
    from flask import request
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset
