"""Response envelope builders (PRD 2.2) and pagination (PRD 2.3).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

import constants
from errors import ApiError


def _now_iso_ms():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(n.microsecond // 1000)


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": _now_iso_ms(),
    }


def ok_obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def pagination_params():
    """Parse limit/offset query params; defaults 10/0, limit clamped to 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else constants.PAGINATION_DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else constants.PAGINATION_DEFAULT_OFFSET
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
    limit = max(constants.PAGINATION_MIN_LIMIT, min(constants.PAGINATION_MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items):
    """items is the full filtered+sorted list; pagination is applied here."""
    limit, offset = pagination_params()
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


def error_response(error_id, message, http_status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status
