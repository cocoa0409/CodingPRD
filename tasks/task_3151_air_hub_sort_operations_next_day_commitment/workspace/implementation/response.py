"""Response envelope helpers (PRD 2.2 / SCAFFOLD 1.0)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ALPHABET = string.ascii_uppercase + string.digits


def generate_request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    return stamp[:-3] + "Z"


def _meta(extra=None):
    meta = {
        "api_request_id": generate_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, response_type="object", pagination=None, status=200):
    meta = _meta(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_object(data, status=200):
    return success(data, "object", None, status)


def success_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return success(items, "array", pagination, 200)


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def normalise_pagination(args):
    """Read limit/offset from query args, applying the declared defaults."""
    try:
        limit = int(args.get("limit", PAGINATION_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = PAGINATION_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", PAGINATION_DEFAULT_OFFSET))
    except (TypeError, ValueError):
        offset = PAGINATION_DEFAULT_OFFSET
    if limit < PAGINATION_MIN_LIMIT:
        limit = PAGINATION_MIN_LIMIT
    if limit > PAGINATION_MAX_LIMIT:
        limit = PAGINATION_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows, args):
    """Sort ascending by created_at, then slice by limit/offset."""
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
    limit, offset = normalise_pagination(args)
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total