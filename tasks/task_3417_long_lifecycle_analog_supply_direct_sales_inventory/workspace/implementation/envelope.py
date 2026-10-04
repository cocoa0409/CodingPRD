# Response envelope helpers (PRD 2.2) and pagination (PRD 2.3).
import uuid

from flask import jsonify, request

import constants as C
from errors import ApiError, ERR_INVALID_REQUEST
from store import store
from timeutil import fmt_iso


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_iso(store.now()),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Query parameter %s must be an integer" % name)


def paginate(items):
    """Apply limit/offset query params to a pre-sorted list.

    Returns (page, limit, offset, total_count). Out-of-range values are
    clamped to the PRD 2.3 bounds (limit 1..100, offset >= 0).
    """
    args = request.args
    limit = C.PAGE_LIMIT_DEFAULT
    offset = C.PAGE_OFFSET_DEFAULT
    if "limit" in args:
        limit = _parse_int_param(args.get("limit"), "limit")
        limit = max(C.PAGE_LIMIT_MIN, min(C.PAGE_LIMIT_MAX, limit))
    if "offset" in args:
        offset = _parse_int_param(args.get("offset"), "offset")
        offset = max(C.PAGE_OFFSET_DEFAULT, offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def list_response(sorted_items, serialize):
    page, limit, offset, total = paginate(sorted_items)
    return success_list([serialize(e) for e in page], limit, offset, total)
