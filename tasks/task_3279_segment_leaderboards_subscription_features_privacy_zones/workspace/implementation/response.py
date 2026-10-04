"""Response envelope helpers, timestamp/id utilities, common-field management."""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def now_iso_ms():
    """Wall-clock timestamp for created_at/updated_at; 3 fractional digits, Z suffix."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def ok_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, status=200):
    total = len(items)
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + limit) < total,
        },
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def touch(rec):
    """Refresh updated_at and bump version on a mutated resource."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = int(rec.get("version", 0)) + 1


def init_common(rec):
    now = now_iso_ms()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    return rec


def parse_pagination(args, default_limit=10, max_limit=100):
    """PRD 2.3: limit defaults 10, range 1..100; offset defaults 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = default_limit
    offset = 0
    limit_explicit = raw_limit is not None
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            from errors import err_validation
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > max_limit:
            from errors import err_validation
            raise err_validation("limit out of range 1..100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            from errors import err_validation
            raise err_validation("offset must be an integer")
        if offset < 0:
            from errors import err_validation
            raise err_validation("offset must be >= 0")
    return limit, offset, limit_explicit


def parse_iso_dt(value):
    """Parse ISO8601 datetime into aware datetime; accepts trailing Z."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse YYYY-MM-DD into a date; returns None when invalid."""
    from datetime import date
    if not isinstance(value, str):
        return None
    try:
        parts = value.strip().split("-")
        if len(parts) != 3:
            return None
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
