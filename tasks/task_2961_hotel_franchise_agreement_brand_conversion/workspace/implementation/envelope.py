"""The response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import json
from decimal import Decimal

from flask import Response, request

from common import D, new_request_id, now_iso
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _plain(value):
    """Render Decimals as JSON numbers; walk containers."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}


def _respond(payload, status):
    body = json.dumps(_plain(payload), allow_nan=False)
    return Response(body, status=status, mimetype="application/json")


def ok(data, status=200):
    return _respond({"meta": _meta(), "response_type": "object", "data": data or {}}, status)


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return _respond({"meta": meta, "response_type": "array", "data": rows}, 200)


def error_response(error):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return _respond(payload, error.http_status)


# ---------------------------------------------------------------------------
# Pagination parameters (PRD 2.3)
# ---------------------------------------------------------------------------


def _as_int(raw):
    text = raw.strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer of at least 0.")
    return limit, offset


def window(rows, limit, offset):
    return rows[offset: offset + limit]
