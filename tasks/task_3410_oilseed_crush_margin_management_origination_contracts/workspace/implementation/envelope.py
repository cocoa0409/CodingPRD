"""Response envelope builders (PRD section 2.2)."""
import random
import string

from flask import jsonify

from store import iso3, wall_now


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": iso3(wall_now())}


def success_obj(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def success_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def success_array(items, status=200):
    """Computed reads that return a bare array (no pagination params)."""
    return jsonify({"meta": _meta(), "response_type": "array", "data": items}), status


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
