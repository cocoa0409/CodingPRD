"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string

from flask import jsonify

import util

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": util.now_iso(),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def paginate(rows, limit, offset):
    """Apply the page window and return (page_rows, total_count, has_more)."""
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, total, offset + len(window) < total


def listing(rows, limit, offset):
    window, total, has_more = paginate(rows, limit, offset)
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = has_more
    return jsonify({"meta": meta, "response_type": "array", "data": window}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
