"""Standard response envelope helpers (scaffold §1.0)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
    return "req_" + tail


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(items, offset, limit):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }