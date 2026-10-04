"""Response envelope helpers per PRD section 2.2 / 2.3."""
import uuid
from datetime import datetime, timezone

from flask import jsonify


def _meta(pagination=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": ts,
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_list(items, limit, offset, total_count):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), 200


def error(err):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }), err.http_status
