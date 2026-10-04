"""Low-level helpers: ids, timestamps, exact Decimal math, and request-body
shape validators (validation priority 4 -> ERR_INVALID_REQUEST, HTTP 400)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request

from errors import ApiError


# ---------------------------------------------------------------- ids / time

def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex.upper()[:24]


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------- Decimal math

def D(value):
    """Exact Decimal from a JSON number (int/float, bool excluded); None if not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    return None


def is_number(v):
    return D(v) is not None


def as_int(v):
    """int value if v is an int (not bool) or an integral float; else None."""
    d = D(v)
    if d is None:
        return None
    if d != d.to_integral_value():
        return None
    return int(d)


def round_half_up(d, places):
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def floor_int(d):
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


def json_number(d):
    """Decimal -> JSON-safe number (int when the Decimal is integral, else float)."""
    if isinstance(d, Decimal):
        if d == d.to_integral_value() and d.as_tuple().exponent >= 0:
            return int(d)
        return float(d)
    return d


# ------------------------------------------------------- body shape helpers

def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", f"Field '{field}': {why}", 400)


def req_present(body, field):
    if field not in body or body[field] is None:
        _bad(field, "is required")
    return body[field]


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or not v:
        _bad(field, "must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not v:
        _bad(field, "must be a non-empty string")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of " + ", ".join(sorted(allowed)))
    return v


def req_number(body, field):
    v = req_present(body, field)
    d = D(v)
    if d is None:
        _bad(field, "must be a number")
    return d


def req_int(body, field):
    v = req_present(body, field)
    iv = as_int(v)
    if iv is None:
        _bad(field, "must be an integer")
    return iv


def opt_bool(body, field, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_dt(body, field):
    v = req_present(body, field)
    dt = parse_dt(v)
    if dt is None:
        _bad(field, "must be an ISO 8601 datetime")
    return dt
