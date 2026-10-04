"""Response envelope helpers (PRD 2.2, 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets

from flask import jsonify

from clock import now, iso_ms


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": iso_ms(now()),
    }


def ok(data, status=200):
    """Single-resource success envelope."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_array(items, status=200):
    """Array success envelope without pagination fields (e.g. carton pack)."""
    return jsonify({"meta": _meta(), "response_type": "array", "data": items}), status


def ok_list(items, limit, offset, total_count, status=200):
    """Paginated list envelope; pagination fields live inside meta (PRD 2.2)."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_response(error_id, status, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
