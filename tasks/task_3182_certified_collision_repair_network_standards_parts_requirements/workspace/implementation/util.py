"""Shared helpers: response envelope, errors, timestamps, pagination, mutation."""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import request

import db as _db


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def now_wall():
    return datetime.now(timezone.utc)


def now_logical():
    return _db.db.clock


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO8601 datetime input into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} must be an ISO8601 timestamp string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       f"{field} is not a valid ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def meta(with_pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(now_wall()),
    }
    if with_pagination:
        m.update(with_pagination)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return body, status


def err_response(error_id, status, message):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, status


def get_json():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def pagination_args():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full filtered+sorted list. Returns (page, pagination_meta)."""
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def bump(entity):
    """Mutation: refresh updated_at and increment version (logical clock)."""
    entity["updated_at"] = iso_ms(now_logical())
    entity["version"] = entity.get("version", 1) + 1


def new_common():
    ts = iso_ms(now_logical())
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": _db.db.next_seq()}


def sort_by_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
