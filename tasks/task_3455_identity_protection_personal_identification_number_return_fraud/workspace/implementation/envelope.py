"""Response envelope helpers (PRD §2.2 / §2.3).

Success: { meta: { api_request_id, api_request_timestamp, [limit, offset,
           total_count, has_more] }, response_type: "object"|"array", data }
Error:   { meta: { api_request_id, api_request_timestamp },
           response_type: "error", data: { error_id, message } }
"""
import random
import string

from flask import jsonify

from store import DB


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta():
    return {
        "api_request_id": _req_id(),
        "api_request_timestamp": DB.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def list_response(items, total_count, limit, offset):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
