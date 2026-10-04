"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
Pagination fields live inside `meta` on list responses only.
"""

import secrets

from flask import jsonify

import store


def _request_id():
    # Server-generated unique id starting with "req_", alphanumeric tail.
    return "req_" + secrets.token_hex(12)


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.iso(store.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, total_count, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
