"""Standard response envelope (PRD 2.2)."""
from flask import jsonify

from store import request_id, wall_ts


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_ts()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
