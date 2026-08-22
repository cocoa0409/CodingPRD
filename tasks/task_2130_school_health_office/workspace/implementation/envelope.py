"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError, fail
from store import request_id

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    now = datetime.now(timezone.utc)
    stamp = "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond // 1000,
    )
    return {"api_request_id": request_id(), "api_request_timestamp": stamp}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {"meta": meta, "response_type": "array", "data": window}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit/offset are validated at ladder position 6 (ERR_INVALID_FIELD_VALUE)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            fail("ERR_INVALID_FIELD_VALUE", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_FIELD_VALUE", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            fail("ERR_INVALID_FIELD_VALUE", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_FIELD_VALUE", "offset must be at least 0.")
    return limit, offset


__all__ = ["ok", "created", "listing", "error_response", "parse_pagination", "ApiError"]
