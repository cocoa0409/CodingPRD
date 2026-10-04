"""Shared helpers: datetime parsing, pagination, entity serialization."""
import math
import uuid
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="datetime"):
    """Parse ISO 8601 datetime string. Raises ERR_INVALID_REQUEST on bad shape."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an ISO8601 string")
    s = value.strip()
    # Accept trailing Z
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, f"{field} is not a valid ISO8601 datetime")
    return dt


def parse_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise err(ERR_INVALID_REQUEST, f"{field} below minimum {minimum}")
    if maximum is not None and value > maximum:
        raise err(ERR_INVALID_REQUEST, f"{field} above maximum {maximum}")
    return value


def parse_str(value, field):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"{field} must be a string")
    return value


def parse_enum(value, field, allowed):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return value


def parse_pagination(args):
    """Read limit/offset from query args with defaults 10/0, bounds 1..100 / >=0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending then slice."""
    items_sorted = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total


def get_or_404(collection, entity_id, label="resource"):
    ent = collection.get(entity_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, f"{label} not found")
    return ent


def require_fields(body, fields):
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be an object")
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"missing required field: {f}")


def ceil_div(a, b):
    return -(-a // b)
