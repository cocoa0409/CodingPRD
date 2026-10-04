"""Response envelope helpers and shared utilities."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    from errors import ApiError, ERR_INVALID_REQUEST
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit out of range", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset out of range", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def parse_iso8601(value):
    """Parse an ISO-8601 datetime string; returns aware datetime or None."""
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


def iso3(dt):
    """Format aware datetime as ISO-8601 with 3 fractional digits and Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
