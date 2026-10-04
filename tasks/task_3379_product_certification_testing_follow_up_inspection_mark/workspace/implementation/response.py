"""Response envelope helpers (PRD 2.2 / 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

import clock
from constants import (
    PAGE_DEFAULT_LIMIT, PAGE_DEFAULT_OFFSET, PAGE_MAX_LIMIT, PAGE_MIN_LIMIT,
)
from errors import ApiError, ERR_INVALID_REQUEST


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _request_timestamp():
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def serialize(value):
    """Recursively serialize an entity: datetimes -> ISO strings, hidden
    underscore-prefixed bookkeeping keys stripped."""
    if isinstance(value, dict):
        return {
            k: serialize(v) for k, v in value.items() if not k.startswith("_")
        }
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return clock.iso(value)
    return value


def _meta(pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": serialize(data),
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """limit/offset query params: defaults 10/0, limit clamped to [1, 100],
    offset clamped to >= 0 (PRD 2.3)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
        limit = max(PAGE_MIN_LIMIT, min(PAGE_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginated_list(items):
    """Slice an already-sorted list and build the pagination meta fields."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination
