"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import datetime

from flask import jsonify

from core import new_request_id


def _meta():
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.")
        + "%03dZ" % (now.microsecond // 1000),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
