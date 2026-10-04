"""Standard response envelope helpers per PRD §2.2 / §2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, err_invalid_request


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Parse limit/offset query params with defaults; enforce min/max."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if isinstance(raw_limit, str) and raw_limit.strip() == "":
        limit = 10
    if isinstance(raw_offset, str) and raw_offset.strip() == "":
        offset = 0
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit out of range (1..100)")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items_sorted):
    """Apply pagination to an already-sorted list."""
    limit, offset = parse_pagination()
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success_list(page, total, limit, offset)


def sort_by_created_at(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
