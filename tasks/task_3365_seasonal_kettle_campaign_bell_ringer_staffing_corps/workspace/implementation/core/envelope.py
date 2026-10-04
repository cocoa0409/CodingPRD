"""Response envelope and pagination (PRD 2.2 / 2.3, scaffold response_envelope).

Success:
  { "meta": {"api_request_id": ..., "api_request_timestamp": ...},
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": {...}, "response_type": "error",
    "data": {"error_id": ..., "message": ...} }

List responses add limit/offset/total_count/has_more to meta.
Pagination defaults: limit 10, min 1, max 100, offset 0.
"""
from flask import jsonify

from . import clock
from .errors import ApiError

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": clock.new_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", meta_extra=None):
    return jsonify({"meta": _meta(meta_extra), "response_type": response_type, "data": data})


def array(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return success(items, "array", meta_extra)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": err.body(),
    }
    return jsonify(body), err.http_status


def read_pagination(args):
    """limit/offset query parameters with the scaffold defaults and bounds."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    try:
        limit = DEFAULT_LIMIT if limit_raw in (None, "") else int(limit_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = DEFAULT_OFFSET if offset_raw in (None, "") else int(offset_raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def page(items, args):
    """Slice an already-sorted list and build the array envelope."""
    limit, offset = read_pagination(args)
    total = len(items)
    window = items[offset:offset + limit]
    return array(window, limit, offset, total)
