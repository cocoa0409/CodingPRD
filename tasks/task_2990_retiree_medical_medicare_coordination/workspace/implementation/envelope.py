"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime

from flask import jsonify, request

from errors import ERR_INVALID_PAGINATION, fail
from store import iso, now

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _api_request_id(),
        "api_request_timestamp": iso(now()),
    }


def _public(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def serialize(record):
    return _public(record)


def object_response(record, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(record) if record is not None else {},
    }
    return jsonify(body), status


def empty_response(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _parse_int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return False
    neg = text.startswith("-")
    digits = text[1:] if neg else text
    if not digits.isdigit():
        return False
    value = int(digits)
    return -value if neg else value


def pagination_params():
    """PRD 2.3 -- limit in [1, 100] default 10, offset >= 0 default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    if raw_limit is not None:
        parsed = _parse_int_param(raw_limit)
        if parsed is False or parsed is None:
            fail(ERR_INVALID_PAGINATION)
        if parsed < PAGINATION_MIN_LIMIT or parsed > PAGINATION_MAX_LIMIT:
            fail(ERR_INVALID_PAGINATION)
        limit = parsed

    if raw_offset is not None:
        parsed = _parse_int_param(raw_offset)
        if parsed is False or parsed is None:
            fail(ERR_INVALID_PAGINATION)
        if parsed < PAGINATION_MIN_OFFSET:
            fail(ERR_INVALID_PAGINATION)
        offset = parsed

    return limit, offset


def paginate(rows):
    limit, offset = pagination_params()
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response(window, limit, offset, total)
