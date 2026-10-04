"""Response envelope helpers (PRD §2.2 success/error envelopes, §2.3 pagination)."""

import random
import string

from flask import jsonify, request

import clock
from errors import ApiError, ERR_INVALID_REQUEST

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def list_ok(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError(ERR_INVALID_REQUEST,
                       "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT), 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def paginate(items, status_filter=None):
    """Optional status filter + created_at-ascending sort + limit/offset window."""
    limit, offset = pagination_params()
    rows = list(items)
    if status_filter is not None:
        rows = [r for r in rows if r.get("status") == status_filter]
    rows.sort(key=lambda r: r["created_at"])  # stable: ties keep insertion order
    total = len(rows)
    page = rows[offset:offset + limit]
    return list_ok(page, limit, offset, total)
