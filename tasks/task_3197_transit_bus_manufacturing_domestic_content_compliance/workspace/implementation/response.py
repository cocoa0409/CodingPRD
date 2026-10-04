"""Response envelope helpers per PRD 2.2 / 2.3."""
import random
import string
from flask import jsonify
from db import fmt_ts, wall_now


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=22))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(wall_now()),
    }


def public(rec):
    """Strip internal keys (underscore-prefixed) from a stored record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def success_obj(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body


def parse_pagination(args):
    """Parse limit/offset query params with PRD 2.3 defaults and bounds."""
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        from errors import err_invalid_request
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        from errors import err_invalid_request
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        from errors import err_invalid_request
        raise err_invalid_request("limit out of range")
    if offset < 0:
        from errors import err_invalid_request
        raise err_invalid_request("offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total
