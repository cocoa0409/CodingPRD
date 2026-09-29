"""Response envelope helpers -- PRD 2.2 / 2.3."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError
from util import fmt_dt, fmt_ms, to_int, wall_now

ALPHANUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

MS_FIELDS = ("created_at", "updated_at")


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ms(wall_now()),
    }


def jsonify_value(value, key=None):
    if isinstance(value, datetime):
        return fmt_ms(value) if key in MS_FIELDS else fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonify_value(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonify_value(v) for v in value]
    return value


def single(payload, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonify_value(payload) if payload is not None else {},
    }
    return jsonify(body), status


def empty(status=200):
    return single({}, status)


def no_content():
    return "", 204


def collection(payload, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(payload)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonify_value(item) for item in payload],
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_page():
    """limit defaults to 10, floor 1, ceiling 100; offset defaults to 0
    (PRD 2.3)."""
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = to_int(raw_limit)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )
    if raw_offset is not None and raw_offset != "":
        try:
            offset = to_int(raw_offset)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginate(records, limit, offset):
    return records[offset : offset + limit]
