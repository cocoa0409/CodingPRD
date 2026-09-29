"""Uniform response envelope (PRD section 2.2 / 2.3)."""

from flask import jsonify

from util import iso, new_request_id
import store


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(store.now()),
    }


def obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def listing(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
