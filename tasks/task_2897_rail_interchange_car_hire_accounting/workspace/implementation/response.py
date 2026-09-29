"""Response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""
import random
import string

from flask import jsonify, request

import db
from errors import fail

ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }


def ok(data, status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.lstrip("+-").isdigit()):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        fail("ERR_INVALID_REQUEST", "%s is out of bounds." % name)
    return value


def page_params():
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows, serializer):
    limit, offset = page_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], total, limit, offset)
