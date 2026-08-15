"""Standard response envelope helpers (PRD §2.2)."""

import uuid

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": db.fmt_ts(db.now()),
    }


def success_obj(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def success_list(items, limit, offset, total_count, has_more, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = has_more
    body = {"meta": meta, "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp
