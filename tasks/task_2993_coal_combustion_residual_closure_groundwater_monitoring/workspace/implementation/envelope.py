"""Standard success and error response envelopes (PRD 2.2, 2.3)."""
import json
from decimal import Decimal

from flask import Response

import store
from errors import ApiError

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


class _Encoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _meta(extra=None):
    meta = {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.iso_instant(store.wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(body, status):
    return Response(
        json.dumps(body, cls=_Encoder),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(row) for row in window],
    }
    return _emit(body, 200)


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _emit(body, err.http_status)


def page_params(args=None):
    """Parse and validate limit/offset (PRD 2.3, precedence position 5)."""
    if args is None:
        from flask import request
        args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def _as_int(raw):
    text = raw.strip() if isinstance(raw, str) else raw
    if isinstance(text, bool) or text == "" or text is None:
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")
