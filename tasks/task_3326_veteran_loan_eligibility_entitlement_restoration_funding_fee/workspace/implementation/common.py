"""Response envelope helpers, clock, ids, rounding utilities."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE


def new_id():
    return str(uuid.uuid4())


def request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_timestamp():
    """Envelope timestamp: ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    """Logical clock as an aware datetime."""
    return parse_iso(STORE.clock_iso)


def clock_now_iso_ms():
    """Logical clock rendered with three fractional digits."""
    dt = clock_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def set_clock(iso_str):
    STORE.clock_iso = iso_str


def parse_iso(value):
    """Parse ISO date/datetime into an aware datetime (UTC assumed when naive)."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round_half_up_int(value):
    """Round a Decimal/fraction to nearest integer, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def envelope_ok(data, response_type, status, pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return body, status


def envelope_error(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": now_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, status


def paginate(items, args):
    """Apply limit/offset pagination. Returns (page, pagination_meta)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pagination


def append_audit(entity_type, entity_id, action, actor_role, actor_user_id, detail):
    eid = new_id()
    event = {
        "id": eid,
        "created_at": now_timestamp(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "detail": detail,
    }
    STORE.audit_events[eid] = event
    return event


def stamp_new(record):
    ts = now_timestamp()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = now_timestamp()
    record["version"] = record.get("version", 1) + 1
    return record


def add_days(dt, days):
    return dt + timedelta(days=days)
