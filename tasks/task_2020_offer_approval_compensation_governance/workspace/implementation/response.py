"""Response envelope helpers per scaffold response_envelope / PRD section 2.2."""

import random
import string
from flask import jsonify

from db import now_ms


def _meta(pagination=None):
    rid = "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": now_ms()}
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
