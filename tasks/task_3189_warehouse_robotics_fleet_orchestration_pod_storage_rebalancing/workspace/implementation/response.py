"""Response envelope helpers, ids, timestamps, pagination."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _ts(dt=None):
    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now():
    return _ts()


def iso_from(dt):
    return _ts(dt)


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success_list(items, limit, offset, total_count, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    if not isinstance(err, ApiError):
        err = ApiError("ERR_VALIDATION", str(err), 400)
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _ts(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def parse_pagination():
    """Parse limit/offset query params per PRD 2.3; raise ERR_VALIDATION on bad shape."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    return limit, offset
