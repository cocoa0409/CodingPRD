"""Standard success / error response envelopes (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify

import db

_ALNUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_str(),
    }


def respond_object(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), http_status


def respond_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def respond_error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(rows, limit, offset):
    """Apply limit/offset to an already-ordered, already-filtered row list."""
    total_count = len(rows)
    page = rows[offset : offset + limit]
    return page, total_count
