"""Response envelope helpers per PRD section 2.2 / 2.3."""
import secrets
from datetime import datetime, timezone
from flask import jsonify

from db import fmt_ts


def _meta(include_pagination=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if include_pagination is not None:
        m["limit"] = include_pagination["limit"]
        m["offset"] = include_pagination["offset"]
        m["total_count"] = include_pagination["total_count"]
        m["has_more"] = include_pagination["has_more"]
    return m


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(include_pagination=page),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def err_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


def parse_pagination(args):
    """Parse limit/offset with defaults: limit default 10 min 1 max 100; offset default 0."""
    from errors import invalid_request
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending, then apply limit/offset. Returns (page_items, limit, offset, total)."""
    items = sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    limit, offset = parse_pagination(args)
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
