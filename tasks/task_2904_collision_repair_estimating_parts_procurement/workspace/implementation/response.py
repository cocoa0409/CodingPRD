"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
from flask import jsonify

import db
from errors import raise_error

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.wall_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(rows, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(rows) < total_count,
        }),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination(args):
    """Validation ladder rung 7 (PRD 2.3)."""
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit)
        if limit is None or limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _as_int(raw_offset)
        if offset is None or offset < 0:
            raise_error("ERR_INVALID_PAGINATION")
    return limit, offset


def _as_int(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return listing([serializer(r) for r in window], limit, offset, total)
