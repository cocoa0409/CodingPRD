"""Response envelope helpers (SCAFFOLD section 1.0 / PRD 2.2, 2.3).

    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
      "response_type": "object" | "array", "data": {} }

Error bodies carry { "error_id", "message" } inside `data` with
"response_type": "error".
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from serialize import clean

_ALNUM = string.ascii_uppercase + string.digits

# SCAFFOLD response_envelope.pagination_defaults
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    """Server-generated wall-clock instant, ISO 8601 UTC, three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": clean(data) if isinstance(data, dict) else data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    """`rows` is the full filtered set in canonical order."""
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [clean(r) for r in window],
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }