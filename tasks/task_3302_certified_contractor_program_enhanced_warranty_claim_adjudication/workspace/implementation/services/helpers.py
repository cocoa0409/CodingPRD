"""Shared helpers: ids, timestamps, dates, pagination, validation."""
import re
import uuid
from datetime import datetime, timezone, date

from errors import ApiError, ERR_INVALID_REQUEST

TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Wall-clock timestamp for created_at/updated_at (3 fractional digits)."""
    n = datetime.now(timezone.utc)
    return n.strftime(TS_FORMAT) + f".{n.microsecond // 1000:03d}Z"


def stamp_common(entity):
    ts = now_ts()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = now_ts()
    entity["version"] += 1
    return entity


# ---- logical clock helpers ----

def parse_clock(iso):
    """Parse logical clock ISO8601 (YYYY-MM-DDTHH:MM:SSZ)."""
    return datetime.strptime(iso, TS_FORMAT + "Z").replace(tzinfo=timezone.utc)


def format_clock(dt):
    return dt.strftime(TS_FORMAT + "Z")


def clock_date(db):
    return parse_clock(db.clock).date()


def valid_iso8601(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, TS_FORMAT + "Z")
        return True
    except (ValueError, TypeError):
        return False


def parse_date(s):
    """Parse YYYY-MM-DD into a date; raises ERR_INVALID_REQUEST on malformed."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Malformed date: {s!r}")
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Malformed date: {s!r}")


def add_months(d, months):
    """Advance date d by N months, clamping day to month end."""
    total = (d.year * 12 + (d.month - 1)) + months
    y, m = divmod(total, 12)
    m += 1
    # days in month
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    dim = (nxt - date(y, m, 1)).days
    return date(y, m, min(d.day, dim))


# ---- request body helpers ----

def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def require_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid value for {field}: {v!r}")
    return v


def require_nonneg_int(data, field):
    v = data.get(field)
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a non-negative integer")
    return v


def require_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a non-empty string")
    return v


def require_string_list(data, field):
    v = data.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} must be a list of strings")
    return v


def parse_pagination():
    """Read limit/offset query params per scaffold defaults (10 / 0, 1..100)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset
