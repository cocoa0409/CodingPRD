"""Response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _int_param(raw):
    """Strict integer parse for a query parameter."""
    text = raw.strip()
    if not text:
        return None
    if text[0] in "+-":
        body = text[1:]
    else:
        body = text
    if not body.isdigit():
        return None
    return int(text)


def pagination():
    """Priority 8: limit is an integer 1..100, offset an integer >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT

    if raw_limit is not None:
        parsed = _int_param(raw_limit)
        if parsed is None or parsed < PAGINATION_LIMIT_MIN or parsed > PAGINATION_LIMIT_MAX:
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        limit = parsed

    if raw_offset is not None:
        parsed = _int_param(raw_offset)
        if parsed is None or parsed < PAGINATION_OFFSET_MIN:
            fail("ERR_INVALID_REQUEST", "offset must be an integer of at least 0.")
        offset = parsed

    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)
