"""Response envelope (PRD section 2.2) and pagination (PRD section 2.3).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
List responses add limit/offset/total_count/has_more to meta.
"""
import secrets
import string

from flask import jsonify, request

import constants as C
import db
import logical_clock
from errors import fail

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": logical_clock.now_iso(),
    }


def ok(data, code=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_args():
    """Parse limit/offset. Defaults 10/0; limit clamped to [1, 100],
    offset clamped to >= 0 (PRD declares min/max but no error for
    out-of-range, so values are clamped rather than rejected)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else C.PAGE_DEFAULT_LIMIT
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else C.PAGE_DEFAULT_OFFSET
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    limit = max(C.PAGE_MIN_LIMIT, min(C.PAGE_MAX_LIMIT, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(collection, predicates=()):
    """Filter + sort + paginate a collection into the standard envelope."""
    items = db.all_recs(collection)
    for pred in predicates:
        items = [r for r in items if pred(r)]
    total = len(items)
    limit, offset = pagination_args()
    page = items[offset:offset + limit]
    return ok(
        [db.public(r) for r in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
    )
