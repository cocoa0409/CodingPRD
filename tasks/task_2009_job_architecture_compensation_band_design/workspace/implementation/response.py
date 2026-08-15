"""Response envelope helpers — exactly per SCAFFOLD.yaml response_envelope."""
import uuid
from datetime import datetime, timezone
from flask import jsonify


def _request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


def _request_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(include_pagination=False, limit=None, offset=None, total_count=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total_count
        m["has_more"] = (offset + limit) < total_count
    return m


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta(True, limit, offset, total_count),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
