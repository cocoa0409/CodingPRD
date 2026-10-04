"""Standard response envelopes (SCAFFOLD section 1.0 / PRD section 2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import uuid

from flask import jsonify

import clock
from validation import pagination_params


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": clock.fmt(clock.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def paginated(items, serializer):
    """Serialize a list endpoint: paginate the (already filtered/sorted)
    items and wrap them in the array envelope."""
    limit, offset = pagination_params()
    total_count = len(items)
    page = items[offset:offset + limit]
    return ok_list([serializer(i) for i in page], limit, offset, total_count)


def error_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status
