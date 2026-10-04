"""Response envelope helpers (PRD §2.2).

Success:  {"meta": {api_request_id, api_request_timestamp[, pagination...]},
           "response_type": "object"|"array", "data": ...}
Error:    {"meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message}}
"""

import random
import string
from flask import jsonify

from db import fmt_ts, STORE


def _req_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + tail


def _meta(pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_ts(STORE.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, response_type="object", pagination=None, status=200):
    return jsonify({
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }), status


def created(data, response_type="object"):
    return ok(data, response_type=response_type, status=201)


def empty(status=200):
    return ok({}, response_type="object", status=status)


def error_body(error_id, message):
    """The error envelope alone; the caller supplies the HTTP status."""
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })