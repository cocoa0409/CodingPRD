"""Response envelope helpers, matching PRD section 2.2 exactly.

Success: {"meta": {api_request_id, api_request_timestamp[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string

from flask import jsonify

import clock


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso_ms(clock.now()),
    }


def success_object(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        status,
    )


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return (
        jsonify({"meta": meta, "response_type": "array", "data": items}),
        200,
    )


def error_payload(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
