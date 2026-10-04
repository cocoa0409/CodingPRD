"""Response envelope helpers and common utilities (timestamps, ids, datetimes, pagination)."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify

from db import STORE
from errors import ApiError, invalid_request


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Wall-clock timestamp for created_at/updated_at (ISO 8601 UTC, 3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def meta_base(extra=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count, status=200):
    m = meta_base({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 UTC datetime string. Raises ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise invalid_request(f"Field {field} must be an ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise invalid_request(f"Malformed datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now():
    """Current logical clock value as a datetime (UTC)."""
    return parse_dt(STORE.clock, "clock")


def parse_pagination(args):
    """Parse limit/offset per spec: limit default 10, min 1, max 100; offset default 0."""
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending and slice; returns (page_items, limit, offset, total)."""
    items_sorted = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    total = len(items_sorted)
    limit, offset = parse_pagination(args)
    page = items_sorted[offset:offset + limit]
    return page, limit, offset, total


def touch(record):
    """Refresh updated_at and bump version on a mutated record."""
    record["updated_at"] = now_ts()
    record["version"] = record.get("version", 1) + 1


def new_common():
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def require_field(body, name):
    if body is None or name not in body or body.get(name) is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def get_json_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request(f"Field {name} must be an integer")
    return value


def require_enum(value, name, allowed):
    if value not in allowed:
        raise invalid_request(f"Invalid enum value for {name}: {value}")
    return value


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def overlaps_half_open(a_start, a_end, b_start, b_end):
    """True iff half-open intervals [a_start,a_end) and [b_start,b_end) overlap."""
    return a_start < b_end and b_start < a_end
