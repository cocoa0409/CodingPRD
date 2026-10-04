"""Response envelope helpers (PRD 2.2) and pagination parsing (PRD 2.3)."""

import random
import string

from flask import jsonify

from errors import ApiError
from timeutil import fmt_dt, now_wall


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


def _meta(pagination=None):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_dt(now_wall()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, code=200):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit defaults 10 (min 1, max 100); offset defaults 0 (min 0).

    Out-of-range values are clamped into the allowed range; non-integer
    values are rejected as ERR_INVALID_REQUEST.
    """
    limit, offset = 10, 0
    raw = args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        limit = max(1, min(100, limit))
    raw = args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def page(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
