"""Response envelope helpers per PRD section 2.2 and pagination per 2.3."""
import secrets
from datetime import datetime, timezone

from flask import jsonify, request

from errors import raise_err, ERR_VALIDATION
from store import (
    serialize, fmt_ts,
    PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT, PAGE_DEFAULT_OFFSET,
)


def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(8),
        # Request metadata timestamp: server wall clock (not the logical clock,
        # which only stamps resource fields per PRD 2.5).
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data)}
    return jsonify(body), status


def ok_list(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": serialize(items),
    }
    return jsonify(body), 200


def err_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, f"query parameter '{name}' must be an integer")
    if value < minimum or value > maximum:
        raise_err(
            ERR_VALIDATION,
            f"query parameter '{name}' must be between {minimum} and {maximum}",
        )
    return value


def paginate(items):
    """Apply limit/offset per PRD 2.3; returns (page_items, pagination_meta)."""
    limit = _query_int("limit", PAGE_DEFAULT_LIMIT, PAGE_MIN_LIMIT, PAGE_MAX_LIMIT)
    offset = _query_int("offset", PAGE_DEFAULT_OFFSET, 0, 2**63 - 1)
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination
