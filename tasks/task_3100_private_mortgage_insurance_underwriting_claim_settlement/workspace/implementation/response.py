"""Standard response envelope (SCAFFOLD section 1.0, PRD 2.2).

    success: { "meta": { "api_request_id", "api_request_timestamp" },
               "response_type": "object" | "array", "data": {} }
    error:   { "meta": {...}, "response_type": "error",
               "data": { "error_id": "...", "message": "..." } }

Pagination fields (limit, offset, total_count, has_more) live inside `meta`
and are present only on list endpoints.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _timestamp():
    # ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4).
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000,)


def meta(**extra):
    payload = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    payload.update(extra)
    return payload


def ok_object(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def ok_array(items, limit, offset, total_count, status=200):
    payload = {
        "meta": meta(
            limit=limit,
            offset=offset,
            total_count=total_count,
            has_more=(offset + len(items)) < total_count,
        ),
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), status


def ok_list(items, status=200):
    """A collection that hangs off a loan carries no limit/offset of its own
    (PRD 2.3), so no pagination fields accompany it."""
    return jsonify({"meta": meta(), "response_type": "array", "data": items}), status


def error(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items, limit, offset):
    """Apply the scaffold's offset pagination: slice after filtering."""
    return items[offset:offset + limit]