"""Shared helpers: input parsing, common-field management, serialization."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from response import iso_utc


def new_id():
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def round2(value):
    """Round to 2 decimal places, round_half_up. Accepts int/float/str/Decimal."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round0(value):
    return Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def to_number(d):
    """Return an int when the Decimal is integral, else float (for JSON)."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def parse_iso(value, field):
    """Parse an ISO 8601 date-time to an aware UTC datetime. Accepts trailing Z."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an ISO 8601 date-time string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} is not a valid ISO 8601 date-time")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_field(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    return body[field]


def opt_field(body, field, default=None):
    if not isinstance(body, dict):
        return default
    return body.get(field, default)


def req_enum(body, field, values):
    v = req_field(body, field)
    if v not in values:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be one of {sorted(values)}")
    return v


def req_number(body, field):
    v = req_field(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a number")
    return v


def req_pos_number(body, field):
    v = req_number(body, field)
    if not (v > 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be > 0")
    return v


def req_int(body, field):
    v = req_field(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an integer")
    return v


def req_nonneg_int(body, field):
    v = req_int(body, field)
    if v < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be non-negative")
    return v


def req_bool(body, field):
    v = req_field(body, field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a boolean")
    return v


def req_string(body, field):
    v = req_field(body, field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be a string")
    return v


def stamp_new(entity):
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity
