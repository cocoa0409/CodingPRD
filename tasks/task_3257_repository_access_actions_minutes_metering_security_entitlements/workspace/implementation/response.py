"""Response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _now_iso(),
    }


def ok(data, status=200, pagination=None):
    m = meta()
    if pagination is not None:
        m.update(pagination)
    body = {
        "meta": m,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items, args):
    """items: list already sorted by created_at ascending. Returns (page, pagination_meta)."""
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        from errors import fail
        fail("ERR_INVALID_REQUEST", "limit/offset must be integers")
    from errors import fail
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative")
    total = len(items)
    page = items[offset:offset + limit]
    pmeta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, pmeta
