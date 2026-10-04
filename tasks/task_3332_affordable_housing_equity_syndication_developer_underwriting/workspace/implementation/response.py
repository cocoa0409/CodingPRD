"""The response envelope (PRD 2.2) and the pagination helpers (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALPHANUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(16))


def wall_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def meta(extra=None):
    payload = {"api_request_id": request_id(), "api_request_timestamp": wall_timestamp()}
    if extra:
        payload.update(extra)
    return payload


def ok(data, status=200, pagination=None):
    """A single-resource (or empty) success envelope."""
    body = {"meta": meta(pagination), "response_type": "object", "data": data}
    return jsonify(body), status


def array(rows, status=200, pagination=None):
    body = {"meta": meta(pagination), "response_type": "array", "data": rows}
    return jsonify(body), status


def error(error_id, message, status):
    body = {"meta": meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


def pagination_args(request):
    """limit defaults to 10 and is clamped to [1, 100]; offset defaults to 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
