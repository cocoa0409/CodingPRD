"""Standard response envelopes (PRD §2.2).

Success:
    { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
      "response_type": "object" | "array", "data": {...} }

Error:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id": "...", "message": "..." } }
"""

from flask import jsonify

from utils import new_request_id, now_iso

# Pagination parameter names and defaults (SCAFFOLD §1.0, PRD §2.3).
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def object_response(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page(records, limit_param, offset_param):
    """Apply offset pagination; raise on an out-of-range limit."""
    from errors import ApiError

    limit = LIMIT_DEFAULT if limit_param in (None, "") else int(limit_param)
    offset = OFFSET_DEFAULT if offset_param in (None, "") else int(offset_param)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError(
            "ERR_INVALID_REFERENCE",
            "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REFERENCE", "offset must not be negative.")
    total = len(records)
    return records[offset:offset + limit], limit, offset, total