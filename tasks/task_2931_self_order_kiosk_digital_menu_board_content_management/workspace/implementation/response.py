"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

import logical_clock as clockmod
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clockmod.now_iso(),
    }


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination(args):
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        text = str(raw_limit).strip()
        if not text.lstrip("-").isdigit():
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = int(text)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        text = str(raw_offset).strip()
        if not text.lstrip("-").isdigit():
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(text)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative")
    return limit, offset
