from flask import request

from errors import err
import store


def list_response(rows, envelope_success):
    """rows: list of serialized dicts in creation order. Returns Flask response."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", 400, "invalid limit")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", 400, "limit out of range")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise err("ERR_INVALID_REQUEST", 400, "invalid offset")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", 400, "invalid offset")
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return envelope_success(200, page, "array", pagination)
