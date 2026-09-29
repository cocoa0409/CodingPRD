"""The standard response envelope."""
from flask import jsonify

from common import iso3, now, request_id


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": iso3(now())}


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def empty_response(status=200):
    return object_response({}, status)


def array_response(items, status=200):
    """An array payload with no pagination window."""
    body = {"meta": _meta(), "response_type": "array", "data": list(items)}
    return jsonify(body), status


def page_response(rows, serializer, limit, offset):
    total = len(rows)
    window = rows[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in window],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
