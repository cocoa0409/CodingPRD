"""Shared helpers: ids, timestamps (logical clock), validation, pagination."""

import uuid
from datetime import datetime, timezone, timedelta

from db import store
from errors import err_invalid_request


def new_id():
    return str(uuid.uuid4())


def logical_now():
    return store.clock


def fmt_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return base + "." + f"{dt.microsecond:06d}".rstrip("0") + "Z"
    return base + "Z"


def parse_dt(value, field):
    """Parse an ISO8601 datetime string. Accepts trailing Z or offset."""
    if not isinstance(value, str) or not value:
        raise err_invalid_request(f"{field} must be an ISO8601 datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise err_invalid_request(f"{field} is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_floor(dt):
    """Truncate to start of day (UTC) for inclusive-day window comparisons."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def require_str(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise err_invalid_request(f"{field} is required and must be a string")
    return v


def require_int(body, field, min_val=None, max_val=None, exclusive_min=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} is required and must be an integer")
    if min_val is not None:
        if exclusive_min and v <= min_val:
            raise err_invalid_request(f"{field} must be > {min_val}")
        if not exclusive_min and v < min_val:
            raise err_invalid_request(f"{field} must be >= {min_val}")
    if max_val is not None and v > max_val:
        raise err_invalid_request(f"{field} must be <= {max_val}")
    return v


def require_number(body, field, min_exclusive=None, max_inclusive=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} is required and must be a number")
    if min_exclusive is not None and not (v > min_exclusive):
        raise err_invalid_request(f"{field} must be > {min_exclusive}")
    if max_inclusive is not None and not (v <= max_inclusive):
        raise err_invalid_request(f"{field} must be <= {max_inclusive}")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def touch(entity):
    entity["updated_at"] = logical_now()
    entity["version"] += 1


def base_entity():
    now = logical_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def paginate(items, args):
    """Parse limit/offset with scaffold defaults and slice."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    return page, limit, offset, total


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))


def serialize(e, extra_nulls=()):
    """Convert internal datetimes to ISO strings for output."""
    out = {}
    for k, v in e.items():
        if k == "opened_by":
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v)
        else:
            out[k] = v
    return out
