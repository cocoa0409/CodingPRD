"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import json
import random
import string

from flask import Response, request

from errors import ApiError, fail
from store import to_json, wall_iso3

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_iso3(),
    }


def _respond(body, status):
    return Response(
        json.dumps(body),
        status=status,
        mimetype="application/json",
    )


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": to_json(data) if data is not None else {},
    }
    return _respond(body, status)


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [to_json(r) for r in rows],
    }
    return _respond(body, 200)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _respond(body, err.http_status)


def pagination():
    """PRD 2.3 — limit defaults to 10 (min 1, max 100), offset defaults to 0.
    Out-of-bounds values are rejected rather than silently clamped."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw_limit).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw_offset).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([_strip(r) for r in page], limit, offset, total)


def _strip(row):
    return {k: v for k, v in row.items() if not str(k).startswith("_")}


def single(row):
    return ok(_strip(row))


def single_created(row):
    return created(_strip(row))


__all__ = [
    "ApiError", "ok", "created", "ok_list", "error_response", "pagination",
    "paginate", "single", "single_created",
]
