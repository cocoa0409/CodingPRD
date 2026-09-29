"""Standard success / error response envelopes (PRD 2.2, 2.3)."""
from flask import jsonify

from util import new_request_id, real_now_iso


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": real_now_iso(),
    }


def obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return obj(data, 201)


def arr(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def unpaginated(rows):
    """Sub-resource list route: no limit/offset accepted (PRD 2.3)."""
    return arr(rows, None, 0, len(rows))


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
