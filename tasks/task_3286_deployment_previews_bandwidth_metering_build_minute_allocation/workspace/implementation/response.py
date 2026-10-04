"""Response envelope helpers per scaffold response_envelope."""

import random
import string
from flask import jsonify
from db import now_iso


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_empty(status=204):
    body = {"meta": meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
