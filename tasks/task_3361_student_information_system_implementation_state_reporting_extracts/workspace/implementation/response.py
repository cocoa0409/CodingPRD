"""Response envelope helpers — exact structure from SCAFFOLD response_envelope.

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination...]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
Pagination fields in meta: limit, offset, total_count, has_more.
"""
import random
import string

from flask import jsonify, request

from db import now_iso
from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok_obj(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_body(error_id, status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_args():
    """Parse limit/offset query params: default 10/0, limit in [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def page_of(items, limit, offset):
    return items[offset:offset + limit]
