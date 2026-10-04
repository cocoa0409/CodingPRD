"""Response envelope helpers (PRD §2.2 / scaffold §1.0).

Success:
    { "meta": {"api_request_id":..., "api_request_timestamp":...},
      "response_type": "object"|"array", "data": {...} }
Error:
    { "meta": {...}, "response_type": "error",
      "data": {"error_id":..., "message":...} }
List responses carry limit/offset/total_count/has_more in meta (PRD §2.3).
"""

from flask import jsonify

from db import ts, request_id, db


def _meta(limit=None, offset=None, total_count=None, has_more=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": ts(db.now()),
    }
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    return jsonify({
        "meta": _meta(limit=limit, offset=offset, total_count=total_count,
                      has_more=(offset + len(items)) < total_count),
        # PRD §2.3: the pagination fields are limit, offset, total_count,
        # has_more; data carries the array of resource objects.
        "response_type": "array",
        "data": items,
    }), 200


def err_body(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status