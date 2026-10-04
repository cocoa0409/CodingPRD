from flask import jsonify, request

from errors import ApiError
from util import iso_now, request_id


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_obj(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


def parse_pagination():
    """limit defaults to 10 (min 1, max 100), offset defaults to 0 (min 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 422, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 422, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 422, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 422, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Records must already be in default sort order (created_at ascending)."""
    total = len(records)
    return records[offset:offset + limit], total


def json_body():
    """Return the request JSON object, or {} when empty. Non-object bodies are 422."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
    return data
