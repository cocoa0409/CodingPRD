"""Standard response envelope helpers."""
from flask import jsonify
import db


def _meta():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, has_more, http_status=200):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = has_more
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
