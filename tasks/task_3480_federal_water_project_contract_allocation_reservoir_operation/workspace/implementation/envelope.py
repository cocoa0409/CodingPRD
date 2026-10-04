"""Response envelope helpers (SCAFFOLD section 1.0, PRD sections 2.2-2.3).

Success: {"meta": {api_request_id, api_request_timestamp, [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
"""
import uuid

from flask import jsonify, request

from errors import ApiError
from store import wallclock_iso

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": wallclock_iso(),
    }


def success(data, code=200):
    payload = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(payload), code


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), 200


def error_response(err):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), err.status


def parse_pagination():
    """Query shape validation: limit in 1..100, offset >= 0 (else 400)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "limit must be between 1 and 100")
    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def list_response(records, serializer, filters=None):
    """Apply exact-match filters, sort by created_at ascending (insertion order
    breaks ties), paginate, and emit the list envelope."""
    filters = filters or {}
    items = [
        r for r in records
        if all(r.get(key) == value for key, value in filters.items() if value is not None)
    ]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)
