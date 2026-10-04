"""Response envelope helpers (PRD §2.2, SCAFFOLD §1.0)."""

import random
import string

from flask import jsonify

from db import now_iso

_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _meta(request_meta=None, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def ok(data, request_meta=None, pagination=None, status=200):
    body = {
        "meta": _meta(request_meta, pagination),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status