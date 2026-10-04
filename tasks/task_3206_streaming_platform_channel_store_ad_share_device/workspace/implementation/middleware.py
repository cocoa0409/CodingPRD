"""Auth header extraction, role checking, pagination, field validation."""

from datetime import datetime, timezone

from flask import request

from db import store
from errors import (
    ERR_INVALID_REQUEST,
    forbidden,
    invalid_request,
    raise_err,
    unauthenticated,
)

VALID_ROLES = {"PlatformAdmin", "AdOps", "Publisher", "Viewer", "TvManufacturer"}


def get_caller():
    """Priority 1: headers present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Priority 2: role permitted on endpoint."""
    user_id, role = get_caller()
    if role not in roles:
        forbidden()
    return user_id, role


def get_json_body():
    """Return the JSON body dict, or {} if none supplied."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        invalid_request("Request body must be a JSON object")
    return body


def parse_pagination():
    """limit/offset with defaults 10/0, bounds 1..100 / >=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if offset < 0:
            invalid_request("offset must be >= 0")
    return limit, offset


def require_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        invalid_request(f"{field} is required and must be a non-empty string")
    return v


def optional_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid_request(f"{field} must be a string")
    return v


def require_int(body, field):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        invalid_request(f"{field} is required and must be an integer")
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        invalid_request(f"{field} must be > 0")
    return v


def require_nonnegative_int(body, field):
    v = require_int(body, field)
    if v < 0:
        invalid_request(f"{field} must be >= 0")
    return v


def require_bool(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, bool):
        invalid_request(f"{field} is required and must be a boolean")
    return v


def optional_bool(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        invalid_request(f"{field} must be a boolean")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


PERIOD_RE_LEN = 7


def require_period(body, field="period"):
    v = require_str(body, field)
    if not is_valid_period(v):
        invalid_request(f"{field} must match YYYY-MM")
    return v


def is_valid_period(s):
    if not isinstance(s, str) or len(s) != 7 or s[4] != "-":
        return False
    try:
        y = int(s[0:4])
        m = int(s[5:7])
    except ValueError:
        return False
    return 1 <= m <= 12 and y >= 1


def parse_iso8601(s, field):
    if not isinstance(s, str) or s == "":
        invalid_request(f"{field} must be an ISO8601 timestamp string")
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        invalid_request(f"{field} must be an ISO8601 timestamp string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def require_datetime(body, field):
    v = body.get(field)
    if v is None:
        invalid_request(f"{field} is required")
    return parse_iso8601(v, field)


def to_iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def period_bounds(period):
    """Return (start_dt, end_dt) for a YYYY-MM period."""
    y = int(period[0:4])
    m = int(period[5:7])
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end
