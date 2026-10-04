"""Response envelope (SCAFFOLD 1.0 / PRD 2.2) and pagination (PRD 2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import api_err


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(now.microsecond // 1000)
    return {"api_request_id": _request_id(), "api_request_timestamp": ts}


def success(data, status=200, pagination=None):
    """Build a success envelope. pagination, when given, is a dict with the
    four pagination fields and marks the payload as an array."""
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
        response_type = "array"
    else:
        response_type = "object"
    resp = jsonify({"meta": meta, "response_type": response_type, "data": data})
    resp.status_code = status
    return resp


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def pagination_params():
    """Parse limit/offset query params per PRD 2.3 (default 10/0, 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise api_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise api_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise api_err("ERR_INVALID_REQUEST", "offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and build the pagination meta fields."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
