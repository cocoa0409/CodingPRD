"""Shared helpers: ids, timestamps, record creation/mutation, body parsing."""
import uuid
from datetime import datetime, timezone

from flask import request

import db
from errors import ApiError

# Resources that carry the full common-field set (updated_at + version).
FULL_COMMON = True


def new_id():
    return str(uuid.uuid4())


_last_ts_ms = [None]


def ts_now():
    """Current logical timestamp, ISO 8601 UTC, 3 fractional digits.

    PRD §3.4 pins creation timestamps as unique ("further ties cannot occur
    because creation timestamps are unique"), so successive calls within the
    same logical millisecond are bumped forward by one millisecond.
    """
    dt = db.now()
    ms = dt.timestamp() * 1000
    ms = int(ms // 1)
    if _last_ts_ms[0] is not None and ms <= _last_ts_ms[0]:
        ms = _last_ts_ms[0] + 1
    _last_ts_ms[0] = ms
    from datetime import datetime as _dt
    out = _dt.fromtimestamp(ms / 1000, tz=timezone.utc)
    return out.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def make_record(full_common=True):
    rec = {
        "id": new_id(),
        "created_at": ts_now(),
    }
    if full_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on mutation (full-common resources)."""
    if "updated_at" in rec:
        rec["updated_at"] = ts_now()
    if "version" in rec:
        rec["version"] += 1


def body_json(required=()):
    """Parse request JSON body; missing required fields -> ERR_INVALID_REQUEST."""
    if not request.data:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Request body required", 400)
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body", 400)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object", 400)
    for field in required:
        if field not in data or data[field] is None:
            raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)
    return data


def parse_iso(value, field="datetime"):
    """Parse an ISO 8601 datetime string to an aware datetime."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string", 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def month_bounds(yyyymm):
    """Return (month_start, month_end_exclusive) as aware datetimes for YYYY-MM."""
    if not isinstance(yyyymm, str) or len(yyyymm) != 7 or yyyymm[4] != "-":
        raise ApiError("ERR_INVALID_REQUEST", "month must be YYYY-MM", 400)
    try:
        y = int(yyyymm[:4])
        m = int(yyyymm[5:7])
        if m < 1 or m > 12:
            raise ValueError
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "month must be YYYY-MM", 400)
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)
