"""Response envelope helpers (PRD 2.2, 2.3).

Success: {"meta": {"api_request_id": "req_...", "api_request_timestamp": ...},
          "response_type": "object" | "array", "data": ...}
List responses add limit / offset / total_count / has_more into meta.
Error:   {"meta": {api_request_id, api_request_timestamp only},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import secrets

from flask import jsonify

from clock import wall_now_iso


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": wall_now_iso(),
    }


def ok(data, code=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), code


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, http_status, message):
    return jsonify(error_body(error_id, message)), http_status


def list_response(sorted_items, limit, offset):
    """Paginate an already-sorted collection into the array envelope."""
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return ok(page, 200, "array", pagination)
