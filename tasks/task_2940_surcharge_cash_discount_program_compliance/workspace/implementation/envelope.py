"""Response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_now():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": request_id(), "api_request_timestamp": _wall_now()}


def _plain(value):
    """Render Decimals as JSON numbers, datetimes are already pre-formatted."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": _plain(data if data is not None else {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": _plain(rows)}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
