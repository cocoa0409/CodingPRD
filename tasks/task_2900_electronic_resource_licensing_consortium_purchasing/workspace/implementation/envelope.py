"""Standard success / error response envelopes and pagination handling."""

from flask import jsonify, request

import store
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination():
    """Read and validate `limit` / `offset` from the query string."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset < PAGINATION_DEFAULT_OFFSET:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def _as_int(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Pagination parameters must be integers.")


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total


def paged(rows):
    """Sort, page and render a collection of rows."""
    limit, offset = pagination()
    ordered = store.sort_rows(rows)
    window, total = paginate(ordered, limit, offset)
    return list_response([store.serialize(r) for r in window], limit, offset, total)
