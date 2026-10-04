"""Time handling, id generation, and the standard response envelope."""
import calendar
import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from store import db


def now():
    """The program logical clock. Never wall-clock time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 string to an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_day(value):
    """Parse and normalize to midnight UTC (date precision at 00:00:00Z)."""
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def success(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(error_id, message):
    meta = {
        "api_request_id": new_req_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    return {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items):
    """Envelope pagination: limit (default 10, 1..100) and offset (default 0)."""
    from errors import ApiError

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
