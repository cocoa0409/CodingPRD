"""Standard response envelope (PRD 2.2) and pagination meta (PRD 2.3)."""

from flask import jsonify

from store import request_id, wall_now_iso


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def respond(data, status=200):
    """Single-resource read or write response: response_type "object"."""
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    """List response: response_type "array" plus the four pagination fields."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
