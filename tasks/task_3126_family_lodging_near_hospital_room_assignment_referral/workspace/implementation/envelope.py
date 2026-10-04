"""Response envelope construction (PRD §2.2, §2.3)."""
import uuid

from flask import jsonify, request

import store
from errors import err, ERR_INVALID_REQUEST


def _meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": store.now_iso(),
    }


def success(data, response_type="object", status=200, pagination=None):
    meta = _meta_base()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(e):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    resp = jsonify(body)
    resp.status_code = e.http_status
    return resp


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3 (default 10, min 1, max 100)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full sorted list. Returns (page, pagination-meta-dict)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def list_response(items):
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)
