"""Response envelope construction and pagination parsing (PRD 2.2, 2.3)."""

from decimal import Decimal

from flask import jsonify, request

from errors import ApiError
from store import request_id, store

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 200


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _plain(data if data is not None else {}),
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": _plain(list(rows)),
    }
    return jsonify(body), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def error_response(exc):
    return error_body(exc.error_id, exc.message, exc.http_status)


def _as_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    negative = text.startswith("-")
    digits = text[1:] if (negative or text.startswith("+")) else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "limit and offset must be integers.")
    value = int(digits)
    return -value if negative else value


def pagination():
    """Returns (limit, offset), enforcing the bounds of PRD 2.3."""
    limit = _as_int(request.args.get("limit"))
    offset = _as_int(request.args.get("offset"))
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError(
            "ERR_INVALID_PAGINATION",
            "limit must be an integer between 1 and 200.",
        )
    if offset is None:
        offset = 0
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer of at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
