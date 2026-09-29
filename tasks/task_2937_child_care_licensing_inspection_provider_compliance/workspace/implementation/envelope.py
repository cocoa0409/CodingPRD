"""Response envelope helpers (PRD §2.2) and pagination parsing (PRD §2.3)."""

import random
import string

from flask import jsonify

import clock
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": clock.now()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(items) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _as_int(raw, label):
    if isinstance(raw, bool) or not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % label)
    text = raw.strip()
    if not text or not (text.lstrip("-+").isdigit()):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % label)
    return int(text)


def pagination(args):
    """Returns (limit, offset), validating the declared bounds."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = LIMIT_DEFAULT if raw_limit is None else _as_int(raw_limit, "limit")
    offset = OFFSET_DEFAULT if raw_offset is None else _as_int(raw_offset, "offset")
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX),
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]
