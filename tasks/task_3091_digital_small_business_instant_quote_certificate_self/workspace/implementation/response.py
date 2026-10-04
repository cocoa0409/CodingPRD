"""Standard response envelope helpers (per scaffold response_envelope)."""
from flask import jsonify

import db


def _meta(paginate=None):
    meta = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.fmt_iso(db.clock_now()),
    }
    if paginate is not None:
        meta["limit"] = paginate["limit"]
        meta["offset"] = paginate["offset"]
        meta["total_count"] = paginate["total_count"]
        meta["has_more"] = paginate["has_more"]
    return meta


def success(data, status=200, response_type="object", paginate=None):
    body = {
        "meta": _meta(paginate),
        "response_type": response_type,
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def ok_object(data, status=200):
    return success(data, status=status, response_type="object")


def ok_array(items, limit, offset, status=200):
    total = len(items)
    page = items[offset:offset + limit]
    paginate = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(page, status=status, response_type="array", paginate=paginate)


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.http_status
    return resp


def parse_pagination(args):
    """limit/offset with defaults 10/0, min 1, max 100."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
