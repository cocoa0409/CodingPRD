"""Response envelope per PRD section 2.2 and pagination per section 2.3.
Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
from flask import jsonify, request
import db
import timeutil
import errors


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": timeutil.fmt(db.now()),
    }


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.status


def page_params():
    """limit: default 10, min 1, max 100. offset: default 0, min 0. Violations -> 400."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            errors.validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.validation("offset must be an integer")
        if offset < 0:
            errors.validation("offset must be >= 0")
    return limit, offset


def paginate(items):
    """items: full filtered list (already created_at ascending). Returns envelope."""
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)
