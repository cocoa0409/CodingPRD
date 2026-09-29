"""Response envelope helpers (PRD 2.2 / 2.3)."""

from flask import jsonify

import store


def _meta():
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.iso(store.wall_now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total, (offset + len(window)) < total


def listing(items, limit, offset, serializer=None):
    window, total, has_more = paginate(items, limit, offset)
    if serializer is not None:
        window = [serializer(r) for r in window]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = has_more
    return jsonify({"meta": meta, "response_type": "array", "data": window}), 200
