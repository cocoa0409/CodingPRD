"""Shared helpers: clock, ids, timestamps, envelope, pagination, auth."""

import os
import random
import string
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, unauthenticated, unauthorized

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_current_time = CLOCK_START


def clock_now():
    return _current_time


def clock_set(dt):
    global _current_time
    _current_time = dt


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=22))
    return "req_" + suffix


def iso3(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_ts():
    return iso3(clock_now())


def parse_dt(value):
    """Parse an ISO 8601 datetime string. Returns aware datetime or raises ValueError."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


VALID_ROLES = {
    "PlatformAdmin",
    "ChartManager",
    "ChartOps",
    "DataProvider",
    "LabelRep",
    "Investigator",
}


def auth_context():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*roles):
    user_id, role = auth_context()
    if role not in roles:
        raise unauthorized()
    return user_id, role


def envelope_ok(data, response_type="object", pagination=None, status=200):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def envelope_error(err):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def pagination_params():
    """Read limit/offset with defaults; returns (limit, offset)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def get_json():
    if not request.data:
        return {}
    try:
        return request.get_json(force=True, silent=False) or {}
    except Exception:
        return {}


def touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_ts()


def new_common():
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
