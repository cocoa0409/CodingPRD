"""Response envelope helpers (PRD section 2.2 / scaffold response_envelope).

Success: {"meta": {"api_request_id", "api_request_timestamp"[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0).
"""

from flask import jsonify, request

from db import clock_now
from errors import ApiError
from util import fmt_ts, new_request_id


def _meta(pagination=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(clock_now()),
    }
    if pagination:
        m.update(pagination)
    return m


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def success_list(items, total, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def parse_pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(sorted_items, serializer):
    limit, offset = parse_pagination()
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    return success_list([serializer(x) for x in page], total, limit, offset)


def sort_default(items):
    """Every list endpoint sorts by created_at ascending; _seq breaks ties in
    insertion order (many resources can share one logical-clock instant)."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
