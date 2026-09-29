"""Response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""
import random
import string

from flask import jsonify

from store import now
from timeutil import fmt_instant

ALNUM = string.ascii_uppercase + string.digits
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": fmt_instant(now())}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
