"""Response envelope helpers per PRD §2.2."""

import secrets
import string

from flask import jsonify, request

from db import real_now_iso
from errors import ApiError, invalid_request


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": real_now_iso(),
    }


def ok_object(data, status=200):
    body = {
        "meta": meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": m,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Parse limit/offset per §2.3 defaults: limit default 10, min 1, max 100; offset default 0."""
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit out of range (1-100)")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list(page, limit, offset, total)


def body():
    """Return the parsed JSON body ({} for empty). Raise ERR_INVALID_REQUEST on malformed JSON."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True)
    except Exception:
        raise invalid_request("Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("JSON body must be an object")
    return data
