"""Response envelope helpers implementing PRD 2.2 exactly.

Success: { "meta": {api_request_id, api_request_timestamp[, pagination...]},
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, invalid_request
from timeutil import iso

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def page_params():
    """Parse limit/offset query params: default 10/0, clamp limit to 1..100."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def ok_list(sorted_items):
    """Paginate an already-sorted list; envelope carries pagination in meta."""
    limit, offset = page_params()
    total = len(sorted_items)
    page = sorted_items[offset : offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


def truthy_param(name):
    raw = request.args.get(name)
    if raw is None:
        return False
    return str(raw).strip().lower() in ("true", "1", "yes")


def sort_items(items):
    """Default list ordering: created_at ascending (insertion seq tiebreak)."""
    return sorted(items, key=lambda e: (e.get("created_at"), e.get("_seq", 0)))
