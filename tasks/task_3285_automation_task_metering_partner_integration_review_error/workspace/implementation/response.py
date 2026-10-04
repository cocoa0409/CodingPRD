"""Response envelope helpers (PRD §2.2, scaffold response_envelope)."""
import random
import string
from datetime import timezone

from flask import jsonify

from clock import Clock


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def _now_iso():
    return Clock.iso_now()


def meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def _with_pagination(extra):
    meta = meta_base()
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    body = {
        "meta": _with_pagination(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items, limit_raw, offset_raw):
    """Apply scaffold pagination defaults and build the meta fragment."""
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset_raw) if offset_raw not in (None, "") else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }