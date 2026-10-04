"""Response envelope builders, matching PRD 2.2 exactly.

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""

import uuid
from datetime import datetime, timezone

from flask import jsonify

from timeutil import fmt


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    """Single-resource success envelope (or empty-object data for 2xx with
    no payload, e.g. the clock endpoint)."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    """List success envelope with pagination fields inside meta."""
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
