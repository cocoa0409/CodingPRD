"""Response envelope helpers (PRD section 2.2) and pagination (PRD section 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ApiError
from store import now_iso

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
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


def ok_list(items, page_meta):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def _parse_page_param(raw, default):
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "" or raw.startswith("+"):
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        value = int(raw, 10)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION")
    if str(value) != raw:
        raise ApiError("ERR_INVALID_PAGINATION")
    return value


def paginate(items):
    """Apply the limit/offset window declared in PRD 2.3 to an ordered list."""
    limit = _parse_page_param(request.args.get("limit"), PAGINATION_DEFAULT_LIMIT)
    offset = _parse_page_param(request.args.get("offset"), PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT or offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
