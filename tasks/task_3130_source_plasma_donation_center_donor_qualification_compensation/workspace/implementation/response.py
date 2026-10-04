"""Standard response envelope helpers per PRD section 2.2 / 2.3."""
import random
import string

from flask import jsonify

import db
from errors import err_invalid_request


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=22))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.ts(),
    }


def success_object(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error.error_id,
            "message": error.message,
        },
    }
    return jsonify(body), error.http_status


def parse_pagination(args):
    """Parse limit/offset query params per PRD 2.3 (defaults 10/0, limit in [1,100])."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
