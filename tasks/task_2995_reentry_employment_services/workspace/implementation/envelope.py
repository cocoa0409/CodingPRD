"""Response envelope helpers — PRD section 2.2."""

import json

from flask import Response

from store import new_request_id, wall_now_str


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_str(),
    }


def _emit(body, status):
    return Response(
        json.dumps(body, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    return _emit(
        {"meta": _meta(), "response_type": "object", "data": data or {}},
        status,
    )


def created(data):
    return ok(data, 201)


def listing(rows, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return _emit({"meta": meta, "response_type": "array", "data": rows}, 200)


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return _emit(error_body(error_id, message), status)
