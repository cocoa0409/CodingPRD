"""Response envelope helpers (PRD 2.2 / scaffold response_envelope)."""
import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
