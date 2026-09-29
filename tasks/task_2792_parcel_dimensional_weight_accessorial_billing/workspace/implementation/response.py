"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def collection(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _parse_pagination_value(raw):
    """Query params arrive as strings; only a plain integer literal is valid."""
    text = raw.strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    value = int(text)
    return value


def pagination_params():
    """Read and validate limit/offset (PRD 2.3)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        parsed = _parse_pagination_value(raw_limit)
        if parsed is None or parsed < PAGINATION_MIN_LIMIT or parsed > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be an integer between 1 and 100 inclusive.")
        limit = parsed

    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        parsed = _parse_pagination_value(raw_offset)
        if parsed is None or parsed < 0:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "offset must be an integer greater than or equal to 0.")
        offset = parsed

    return limit, offset


def paginate(records, serializer, limit=None, offset=None):
    """Apply pagination to an already-ordered, already-filtered record list."""
    if limit is None or offset is None:
        limit, offset = pagination_params()
    total = len(records)
    window = records[offset:offset + limit]
    return collection([serializer(r) for r in window], total, limit, offset)
