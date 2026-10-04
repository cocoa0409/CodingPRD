"""Shared helpers: ids, timestamps, pagination, validation."""
import uuid
from datetime import datetime, timezone, timedelta

import db
import errors


def new_id():
    return str(uuid.uuid4())


def stamp():
    """ISO timestamp from the logical clock, 3 fractional digits."""
    dt = db.clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def monday_of_week(dt):
    """Return Monday (date) of the week containing dt."""
    d = dt.date()
    return (d - timedelta(days=d.weekday())).isoformat()


def parse_iso(s):
    """Parse ISO-8601 string (with Z or offset) into aware datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_or_404(store, rid):
    if rid not in store:
        raise errors.err_not_found(f"Resource {rid} not found")
    return store[rid]


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or not v:
        raise errors.err_invalid_request(f"Field {field} is required and must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_invalid_request(f"Field {field} is required and must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"Field {field} must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field, default)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err_invalid_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"Field {field} must be >= {minimum}")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise errors.err_invalid_request(f"Field {field} is required and must be a boolean")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise errors.err_invalid_request(f"Field {field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def paginate(items, args):
    """Apply limit/offset per envelope spec; returns (page, pagination_meta)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.err_invalid_request("limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.err_invalid_request("limit out of range")
    if offset < 0:
        raise errors.err_invalid_request("offset out of range")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))
