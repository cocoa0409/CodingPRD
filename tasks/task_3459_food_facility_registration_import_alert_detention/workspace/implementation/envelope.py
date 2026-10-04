"""Response envelope helpers (SCAFFOLD section 1.0 / PRD section 2.2)."""
import uuid

from flask import jsonify, request

import db


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": db.wall_now_iso(),
    }


def ok(data, code=200):
    """Single-resource (or free-form object) success envelope."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset):
    """Paginated list success envelope."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def json_body():
    """Request JSON object; a missing or non-object body becomes {}."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}
