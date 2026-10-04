"""Response envelope helpers (PRD section 2.2 / 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import uuid
from flask import jsonify

import clock


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": clock.fmt(clock.now()),
    }


def obj(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def arr(items, total, limit, offset, code=200):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), code


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def parse_pagination(args):
    def _as_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    limit = _as_int(args.get("limit"), 10)
    offset = _as_int(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def page(items, args):
    """Sort must already be applied; this slices and wraps the envelope."""
    limit, offset = parse_pagination(args)
    total = len(items)
    return arr(items[offset:offset + limit], total, limit, offset)
