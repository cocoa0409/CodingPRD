"""Standard response envelope helpers (SCAFFOLD response_envelope, PRD §2.2)."""

import random
import string
from flask import jsonify

import db


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.utcnow().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }


def success_object(data, status_code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count, status_code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status_code


def error(error_id, message, status_code):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status_code
