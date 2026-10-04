"""Response envelope helpers per scaffold §1.0 and PRD §2.2/§2.3."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

# Fixed per-request wall-clock timestamp for the envelope meta only
# (business logic always reads the logical clock from db.py).


def _request_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_z(dt):
    if dt is None:
        return None
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + secrets.token_hex(12),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": "req_" + secrets.token_hex(12),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": "req_" + secrets.token_hex(12),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset with scaffold defaults: limit default 10, min 1,
    max 100, offset default 0."""
    from errors import validation

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            validation("limit must be an integer")
        if limit < 1 or limit > 100:
            validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            validation("offset must be an integer")
        if offset < 0:
            validation("offset must be >= 0")
    return limit, offset


def paginate(items_sorted, limit, offset):
    total = len(items_sorted)
    return items_sorted[offset:offset + limit], total
