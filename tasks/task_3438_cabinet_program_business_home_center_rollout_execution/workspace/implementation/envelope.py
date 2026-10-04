"""PRD 2.2/2.3 response envelope and pagination."""
from flask import jsonify, request

from errors import api_error
from util import new_request_id, now_iso


def _meta(pagination=None):
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items):
    """Apply limit/offset per PRD 2.3 (default 10, min 1, max 100; offset default 0).

    Returns (page_items, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise api_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
