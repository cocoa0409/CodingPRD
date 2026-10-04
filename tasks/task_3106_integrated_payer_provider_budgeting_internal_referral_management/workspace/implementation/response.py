"""Response envelope helpers.

PRD 2.2 fixed envelope:

  success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": ..., "message": ... } }

Pagination fields (PRD 2.3) live in `meta` on list responses.
"""

import random
import string

from clock import CLOCK
from constants import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
)
from errors import ERR_INVALID_STATE, ApiError
from rounding import number_out

_ALPHABET = string.ascii_uppercase + string.digits


def new_request_id():
    suffix = "".join(random.choice(_ALPHABET) for _ in range(12))
    return "req_" + suffix


def _meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": CLOCK.now_iso(),
    }


def success(payload, response_type="object", pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return {"meta": meta, "response_type": response_type,
            "data": serialize(payload)}


def success_list(items, pagination):
    return success([serialize(item) for item in items], "array", pagination)


def error_body(error_id, message):
    body = {"meta": _meta_base(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return body


def parse_pagination(query):
    """Read limit/offset from the query string. Out-of-bounds values are not
    silently clamped into an unbounded page: they are refused (PRD 2.3)."""
    limit_raw = query.get("limit")
    offset_raw = query.get("offset")
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    if limit_raw is not None and str(limit_raw) != "":
        try:
            limit = int(str(limit_raw))
        except (TypeError, ValueError):
            limit = -1
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "limit must be between %d and %d."
                           % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX), 400)
    if offset_raw is not None and str(offset_raw) != "":
        try:
            offset = int(str(offset_raw))
        except (TypeError, ValueError):
            offset = -1
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "offset must not be negative.", 400)
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def serialize(item):
    """Convert a stored row (or list of rows) into a JSON-ready structure."""
    if item is None:
        return {}
    if isinstance(item, list):
        return [serialize(entry) for entry in item]
    if isinstance(item, dict):
        out = {}
        for key, value in item.items():
            if isinstance(value, list):
                out[key] = [serialize(entry) for entry in value]
            elif isinstance(value, dict):
                out[key] = serialize(value)
            else:
                out[key] = number_out(value)
        return out
    return item


def _unused_invalid_state():
    return ERR_INVALID_STATE