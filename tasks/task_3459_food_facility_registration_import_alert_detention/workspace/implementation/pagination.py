"""Pagination helpers (PRD section 2.3).

limit defaults to 10, minimum 1, capped at 100; offset defaults to 0.
Lists are sorted by creation timestamp ascending (with a total server-side
creation-order tie-break applied by the callers via db.sort_key).
"""
from flask import request

from errors import ApiError

DEFAULT_LIMIT = 10
MAX_LIMIT = 100


def page_params():
    raw_limit = request.args.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be at least 1")
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
    raw_offset = request.args.get("offset")
    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    """Return (total_count, page_slice) for an already-sorted list."""
    total = len(items)
    return total, items[offset : offset + limit]
