"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

from flask import jsonify, request

from db import now, public
from errors import ApiError
from util import iso, new_request_id

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso(now()),
    }


def envelope(response_type, data, extra_meta=None):
    meta = _meta()
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": response_type, "data": data}


def object_response(row, status=200):
    data = public(row) if isinstance(row, dict) and "id" in row else row
    return jsonify(envelope("object", data if data is not None else {})), status


def raw_response(data, status=200):
    return jsonify(envelope("object", data)), status


def list_response(rows, limit, offset, total_count):
    data = [public(row) for row in rows]
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(data) < total_count,
    }
    return jsonify(envelope("array", data, extra)), 200


def error_response(error_id, message, status):
    body = envelope("error", {"error_id": error_id, "message": message})
    return jsonify(body), status


def pagination_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")

    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")

    return limit, offset


def paginate(rows):
    """Apply the pagination window and emit the list envelope."""
    limit, offset = pagination_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response(window, limit, offset, total)
