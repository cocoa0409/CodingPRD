"""Response envelope helpers."""
import uuid
from datetime import datetime

from flask import jsonify

from clock import now_iso, to_iso
from errors import ApiError


def _serialize(value):
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": _serialize(data),
    }
    return jsonify(body), status


def error_response(e):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Not found", 404))

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))

    @app.errorhandler(Exception)
    def _unhandled(e):
        return error_response(ApiError("ERR_INVALID_REQUEST", str(e), 500))


def parse_pagination(args):
    from errors import err

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, args):
    limit, offset = parse_pagination(args)
    items = sorted(items, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
