"""Response envelope helpers (PRD §2.2).

Success:  {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
           "response_type": "object" | "array", "data": ...}
Error:    {"meta": {"api_request_id", "api_request_timestamp"},
           "response_type": "error", "data": {"error_id", "message"}}
"""
import uuid

from flask import jsonify

from db import STORE


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": STORE.now_iso(),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_envelope(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
