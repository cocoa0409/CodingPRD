"""Response envelope helpers -- PRD section 2.2 and 2.3, verbatim field names."""

import random
import string

from flask import jsonify, request

import db
from errors import fail

# PRD section 2.3
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_ID_ALPHABET = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso(db.now()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_query(name, default, minimum, maximum):
    raw = request.args.get(name, None)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text, 10)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def pagination():
    """PRD section 2.3 -- limit 1..100 (default 10), offset >= 0 (default 0).

    Out-of-range values are refused with ERR_INVALID_REQUEST, never clamped.
    """
    limit = _int_query("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_query("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginated(records, serializer, limit, offset):
    total = len(records)
    window = records[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)
