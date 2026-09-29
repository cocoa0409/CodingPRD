"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify, request

import store
from errors import fail
from util import new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": store.clock_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination():
    """limit default 10 (min 1, max 100); offset default 0 (non-negative)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must not be negative")
    return limit, offset


def paginate(items, serializer):
    limit, offset = read_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return ok_list([serializer(row) for row in window], limit, offset, total)
