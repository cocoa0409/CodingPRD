# Response envelope (PRD 2.2) — exact shapes:
#   success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
#   error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
# List responses add limit/offset/total_count/has_more into meta (PRD 2.3).
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _request_meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": rid, "api_request_timestamp": ts}


def success(data, response_type="object", status=200, pagination=None):
    body = {"meta": _request_meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_response(api_err):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.http_status


def paginate(items, args):
    """Offset pagination (PRD 2.3): limit default 10 (min 1, max 100), offset
    default 0. Returns (page, pagination_meta). Raises ApiError on bad params."""
    from errors import err

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if isinstance(raw_limit, str) and raw_limit.strip().lstrip("+-").isdigit() is False:
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            raise err("ERR_INVALID_REQUEST", "limit must be at least 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if isinstance(raw_offset, str) and raw_offset.strip().lstrip("+-").isdigit() is False:
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be at least 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
