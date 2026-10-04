"""Response envelope helpers (PRD §2.2 / scaffold §1.0, verbatim shapes).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields live inside meta: limit, offset, total_count, has_more.
"""
from flask import jsonify

from store import DB, new_request_id, ts3


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": ts3(DB.now()),
    }


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_array(items, status=200):
    """Non-paginated array response (bulk creation results)."""
    return jsonify({"meta": _meta(), "response_type": "array", "data": items}), status


def ok_list(items, total_count, limit, offset, status=200):
    """Paginated list response; pagination fields ride inside meta."""
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), status


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.status
