"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def new_api_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now_iso():
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond // 1000,
    )


def _base_meta():
    return {
        "api_request_id": new_api_request_id(),
        "api_request_timestamp": _wall_now_iso(),
    }


def object_response(data, http_status=200):
    body = {"meta": _base_meta(), "response_type": "object", "data": data}
    return jsonify(body), http_status


def array_response(items, limit, offset, total_count, http_status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), http_status


def error_response(error_id, message, http_status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_pagination_int(raw, name, minimum, maximum):
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_REQUEST", "%s is out of range" % name)
    return value


def read_pagination(args):
    """limit/offset from the query string. Out-of-bounds is malformed, never clamped."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        limit = _parse_pagination_int(args.get("limit"), "limit", LIMIT_MIN, LIMIT_MAX)
    if "offset" in args:
        offset = _parse_pagination_int(args.get("offset"), "offset", OFFSET_MIN, None)
    return limit, offset


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
