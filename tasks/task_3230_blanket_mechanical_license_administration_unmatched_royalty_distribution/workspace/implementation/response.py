"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError


def _now_iso():
    """Wall-clock timestamp with exactly 3 fractional digits for meta."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": _now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, code=200):
    """Paginated list response. Pagination params parsed from query string."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "pagination out of range", 400)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": page,
    }
    return jsonify(body), code


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
