"""Response envelope (PRD 2.2) and pagination meta (PRD 2.3)."""
from __future__ import annotations

from flask import jsonify

from util import iso, new_request_id, wall_now


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(wall_now()),
    }


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, page):
    meta = _meta()
    meta["limit"] = page["limit"]
    meta["offset"] = page["offset"]
    meta["total_count"] = page["total_count"]
    meta["has_more"] = page["has_more"]
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
