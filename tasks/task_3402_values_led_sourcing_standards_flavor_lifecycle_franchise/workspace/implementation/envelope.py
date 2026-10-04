"""Standard success/error response envelope helpers (PRD section 2.2).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more to meta.
"""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail
from timeutil import fmt_wall


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_wall(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    """Single-resource success envelope (or empty object for no-data 2xx)."""
    if data is None:
        data = {}
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def pagination_args():
    """Parse limit/offset per PRD 2.3: default 10/0, limit clamped to [1,100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def ok_list(items, limit, offset):
    """Array envelope with pagination fields in meta."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def err(error_id, http_status, message):
    """Error envelope: meta carries only request id and timestamp."""
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
