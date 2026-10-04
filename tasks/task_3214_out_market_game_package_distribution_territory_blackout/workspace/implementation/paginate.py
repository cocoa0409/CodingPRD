"""Pagination helpers per scaffold §1.0: limit/offset/total_count/has_more."""
from flask import request

from errors import err_invalid_request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Parse limit/offset query params with defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err_invalid_request("limit out of bounds")
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must not be negative")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and build the pagination meta fields."""
    total = len(items)
    window = items[offset:offset + limit]
    has_more = offset + len(window) < total
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
