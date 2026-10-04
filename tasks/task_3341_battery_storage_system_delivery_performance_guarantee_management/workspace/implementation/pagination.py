"""Pagination helper shared by all list routes."""
from flask import request

from errors import ApiError


def paginate_params():
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = paginate_params()
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
