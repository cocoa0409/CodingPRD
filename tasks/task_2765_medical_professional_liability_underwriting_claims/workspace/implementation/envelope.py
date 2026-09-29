"""Response envelope helpers (PRD 2.2) and offset pagination (PRD 2.3)."""
from flask import jsonify, request

import constants as C
from errors import ApiError
from store import flush, now_iso, request_id, to_json


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def _envelope(data, response_type, status, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": to_json(data),
    }
    return jsonify(body), status


def ok(data, status=200):
    flush()
    return _envelope(data if data is not None else {}, "object", status)


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    flush()
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return _envelope(list(items), "array", 200, meta)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --- pagination -------------------------------------------------------------
def _int_arg(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_PAGINATION_INVALID", "%s must be an integer." % name)
    try:
        if text.startswith("+"):
            text = text[1:]
        negative = text.startswith("-")
        digits = text[1:] if negative else text
        if not digits.isdigit():
            raise ValueError(text)
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_PAGINATION_INVALID", "%s must be an integer." % name)
    return value


def pagination():
    """Parse and validate limit/offset, returning the effective values."""
    limit = _int_arg(request.args.get("limit"), "limit")
    offset = _int_arg(request.args.get("offset"), "offset")
    if limit is None:
        limit = C.LIMIT_DEFAULT
    elif limit < C.LIMIT_MIN or limit > C.LIMIT_MAX:
        raise ApiError(
            "ERR_PAGINATION_INVALID",
            "limit must be between %d and %d." % (C.LIMIT_MIN, C.LIMIT_MAX),
        )
    if offset is None:
        offset = C.OFFSET_DEFAULT
    elif offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", "offset may not be negative.")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    window = records[offset : offset + limit]
    return window, total


def listing(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return ok_list(window, limit, offset, total)
