"""Standard response envelope (PRD 2.2).

Success:
    {"meta": {"api_request_id": ..., "api_request_timestamp": ...},
     "response_type": "object" | "array", "data": {...}}

List responses add limit/offset/total_count/has_more to meta.
Error:
    {"meta": {...}, "response_type": "error",
     "data": {"error_id": ..., "message": ...}}
"""

from flask import jsonify

import storage

PAGINATION_DEFAULTS = {"limit": 10, "min_limit": 1, "max_limit": 100, "offset": 0}


def _meta(extra=None):
    meta = {
        "api_request_id": storage.request_id(),
        "api_request_timestamp": storage.utc_now_stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-resource success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(items)) < total_count,
            }
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination parsing (limit 10 default, 1..100 inclusive; offset 0 default)
# ---------------------------------------------------------------------------
def paginate(items, args):
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = PAGINATION_DEFAULTS["limit"]
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = PAGINATION_DEFAULTS["limit"]
        limit = max(PAGINATION_DEFAULTS["min_limit"],
                    min(PAGINATION_DEFAULTS["max_limit"], limit))

    offset = PAGINATION_DEFAULTS["offset"]
    if offset_raw is not None:
        try:
            offset = max(0, int(offset_raw))
        except (TypeError, ValueError):
            offset = PAGINATION_DEFAULTS["offset"]

    total_count = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total_count