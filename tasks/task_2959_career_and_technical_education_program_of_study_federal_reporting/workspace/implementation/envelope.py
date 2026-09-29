"""Response envelope helpers (PRD sec 2.2 / scaffold response_envelope)."""
from flask import jsonify

from store import request_id, wall_stamp


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": wall_stamp()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page(rows, limit, offset):
    """Apply the page window and return (window_rows, total_count)."""
    total = len(rows)
    return rows[offset:offset + limit], total
