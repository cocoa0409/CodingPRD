"""Standard response envelope (PRD 2.2)."""
import uuid

from flask import jsonify

from db import now_wall
from util import fmt_wall


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_wall(now_wall()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return (
        jsonify({"meta": _meta(pagination), "response_type": "array", "data": items}),
        200,
    )


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
