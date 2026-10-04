"""Standard response envelope (PRD 2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, http_status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), http_status


def array_response(records, limit, offset, http_status=200):
    total = len(records)
    window = records[offset:offset + limit]
    has_more = (offset + len(window)) < total
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": window,
    }), http_status


def error_response(error):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error.error_id,
            "message": error.message,
        },
    }), error.http_status
