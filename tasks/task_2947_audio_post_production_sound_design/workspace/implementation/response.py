"""Response envelope helpers (PRD §2.2, scaffold response_envelope)."""

import random
import string

from flask import jsonify

import clock

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    """PRD §2.2: 'api_request_id always starts with the prefix req_'."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt_millis(clock.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def empty_response(status=200):
    return object_response({}, status)


def list_response(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(records, limit, offset):
    """Returns (window, total_count).  total_count counts matches before the window."""
    total = len(records)
    return records[offset:offset + limit], total
