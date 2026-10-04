"""Response envelope (SCAFFOLD Table 1.0 / PRD 2.2) and pagination (PRD 2.3)."""
import uuid

from flask import jsonify, request

from clock import now_iso
from errors import fail


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def success_list(items, code=200):
    """items must already be filtered and sorted; pagination is applied here."""
    page, total, limit, offset = paginate(items)
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), code


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items):
    """limit defaults 10 (clamped to [1,100]); offset defaults 0 (>=0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    total = len(items)
    return items[offset:offset + limit], total, limit, offset


def sort_default(items):
    """Default list sort: created_at ascending, commit order as tiebreak."""
    return sorted(items, key=lambda e: (e["created_at"], e["seq"]))
