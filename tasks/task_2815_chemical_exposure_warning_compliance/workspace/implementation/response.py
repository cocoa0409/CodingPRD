"""The standard response envelope (PRD 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail
from util import fmt_dt

_ALNUM = string.ascii_uppercase + string.digits

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 200
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination():
    """limit/offset with the declared defaults, minima and maximum (PRD 2.3)."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
    if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 200")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def page(items, limit, offset):
    return items[offset:offset + limit]
