"""Standard response envelope (PRD §2.2 / SCAFFOLD response_envelope)."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + tail


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def meta(pagination=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200, pagination=None):
    body = {
        "meta": meta(pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def empty(status=200):
    return ok({}, status=status)


def fail(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items, params):
    """limit/offset pagination; limit default 10 min 1 max 100; offset default 0."""
    limit = params.get("limit", 10)
    offset = params.get("offset", 0)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    window = items[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }