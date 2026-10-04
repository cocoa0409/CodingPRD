"""Standard response envelope (PRD 2.2, SCAFFOLD section 1.0)."""

import random
import string

from flask import jsonify

from db import db

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choices(_ALPHABET, k=16))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": db.now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_empty(status=200):
    return ok({}, status)


def ok_list(items, limit, offset, total_count):
    has_more = offset + len(items) < total_count
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    """Render an ApiError with its catalogued HTTP status (PRD 2.2, 5)."""
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status
