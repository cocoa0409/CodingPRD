"""Response envelope helpers."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def success(data, status=200, is_list=False, pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": db.now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def paginate(items):
    """Apply limit/offset query params to a list. Returns (page, pagination_meta)."""
    from errors import raise_err
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise_err("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err("ERR_VALIDATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_VALIDATION", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def sorted_by_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
