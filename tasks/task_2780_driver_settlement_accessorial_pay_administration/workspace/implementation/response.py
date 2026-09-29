"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""
import random
import string

from flask import jsonify

import clock
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _parse_page_int(raw, name):
    if isinstance(raw, bool):
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be an integer." % name)
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if text == "":
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_FIELD_VALUE", "%s must be an integer." % name)
    value = int(text)
    return value


def pagination(args):
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if "limit" in args and args.get("limit") is not None:
        limit = _parse_page_int(args.get("limit"), "limit")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_FIELD_VALUE",
                "limit must be between %d and %d." % (MIN_LIMIT, MAX_LIMIT),
            )
    if "offset" in args and args.get("offset") is not None:
        offset = _parse_page_int(args.get("offset"), "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_FIELD_VALUE", "offset may not be negative.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total
