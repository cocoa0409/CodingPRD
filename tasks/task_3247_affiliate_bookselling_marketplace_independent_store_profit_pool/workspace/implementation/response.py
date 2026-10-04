"""Standard response envelope helpers."""
import random
import string

from flask import jsonify

import db
from errors import ApiError, err_validation


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def make_meta(pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": db.now_wall_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_empty(status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": make_meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset from query args per PRD 2.3."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit out of range [1, 100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending and apply limit/offset."""
    items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
