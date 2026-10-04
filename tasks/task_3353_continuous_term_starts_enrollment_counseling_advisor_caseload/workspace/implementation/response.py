"""Standard response envelope helpers (PRD §2.2 / SCAFFOLD response_envelope).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error",
          "data": {"error_id": ..., "message": ...}}
Pagination fields live in meta: limit, offset, total_count, has_more.
"""

import uuid
from flask import jsonify

from store import now_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_ts(),
    }


def ok_object(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_empty(status=200):
    return ok_object({}, status)


def ok_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), status


def err_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
