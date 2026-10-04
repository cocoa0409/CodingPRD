"""Response envelope and pagination helpers (PRD 2.2 / 2.3, scaffold 1.0).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
          total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string
from datetime import date, datetime, timezone

from flask import jsonify, request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import ApiError, err_invalid_request
from util import fmt_dt


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _wall_ts():
    # Envelope timestamp: real receipt time (the logical clock is for business
    # rules only, PRD 2.4).
    return fmt_dt(datetime.now(timezone.utc))


def serialize(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def ok_object(data, code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "object",
        "data": serialize(data),
    }
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    page = items[offset:offset + limit]
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(page) < total_count,
        },
        "response_type": "array",
        "data": serialize(page),
    }
    return jsonify(body), 200


def error_response(exc):
    if isinstance(exc, ApiError):
        error_id, status, message = exc.error_id, exc.http_status, exc.message
    else:
        error_id, status, message = "ERR_INVALID_REQUEST", 500, str(exc)
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _wall_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    """Parse and validate limit/offset query parameters (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err_invalid_request("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            err_invalid_request("limit out of range")
    if raw_offset is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err_invalid_request("offset must be an integer")
        if offset < 0:
            err_invalid_request("offset must be >= 0")
    return limit, offset


def apply_filters(items, allowed_fields):
    """Exact-match query filters restricted to the endpoint's declared fields."""
    active = {f: request.args.get(f) for f in allowed_fields if request.args.get(f) is not None}
    if not active:
        return list(items)
    out = []
    for item in items:
        keep = True
        for field, wanted in active.items():
            if str(item.get(field)) != wanted:
                keep = False
                break
        if keep:
            out.append(item)
    return out


def list_page(items):
    """Sort (created_at ascending, PRD 2.3) and paginate a filtered list."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    return ok_list(ordered, limit, offset, len(ordered))
