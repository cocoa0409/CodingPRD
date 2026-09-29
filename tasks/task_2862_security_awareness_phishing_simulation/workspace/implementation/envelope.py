"""Response envelope helpers (PRD section 2.2)."""
import random
import string

from flask import jsonify

from store import fmt, now

ALNUM = string.ascii_uppercase + string.digits


def _meta():
    suffix = "".join(random.choice(ALNUM) for _ in range(20))
    return {
        "api_request_id": "req_" + suffix,
        "api_request_timestamp": fmt(now()),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
