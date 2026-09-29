"""Response envelope helpers (PRD 2.2 / 2.3)."""

import json

from flask import Response

import store

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.iso(store.now()),
    }


def _respond(payload, http_status):
    body = json.dumps(payload)
    return Response(body, status=http_status, mimetype="application/json")


def object_response(data, http_status=200):
    return _respond(
        {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}},
        http_status,
    )


def created(data):
    return object_response(data, 201)


def no_content():
    return Response("", status=204)


def array_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return _respond({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, http_status):
    return _respond(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        http_status,
    )
