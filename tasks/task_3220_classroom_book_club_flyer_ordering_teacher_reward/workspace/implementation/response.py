"""Standard success response envelope helpers."""

import uuid
from flask import jsonify, request

import db
from errors import raise_err


def envelope(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": db.now_iso_ms(),
        },
        "response_type": response_type,
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def object_response(data, status=200):
    return envelope(data, "object", status)


def list_response(items, status=200):
    """items: (page_slice, total_count, limit, offset)"""
    page, total, limit, offset = items
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return envelope(page, "array", status, pagination)


def parse_pagination():
    """Parse limit/offset query params with scaffold defaults: limit 10 (1..100), offset 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items_sorted):
    limit, offset = parse_pagination()
    total = len(items_sorted)
    page = items_sorted[offset : offset + limit]
    return page, total, limit, offset
