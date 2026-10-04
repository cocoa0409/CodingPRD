"""Standard response envelope helpers (PRD §2.2)."""
import secrets

from flask import jsonify

from db import now_iso


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(data, limit, offset, total_count, status=200):
    has_more = (offset + len(data)) < total_count
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": data}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset per PRD §2.3: limit default 10, min 1, max 100;
    offset default 0."""
    from errors import validation

    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit out of range (1..100)")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    return items[offset:offset + limit]
