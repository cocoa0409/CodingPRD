"""Response envelope (PRD 2.2) and pagination (PRD 2.3) helpers."""
import uuid

from flask import jsonify, request

import clock
from constants import (
    PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX, PAGE_OFFSET_DEFAULT,
)


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": clock.iso(),
    }


def public(rec):
    """Strip internal '_' keys recursively for serialization."""
    if isinstance(rec, dict):
        return {k: public(v) for k, v in rec.items() if not k.startswith("_")}
    if isinstance(rec, list):
        return [public(x) for x in rec]
    return rec


def ok(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_object(record, status=200):
    return ok(public(record), "object", status)


def ok_list(records, total, page):
    return ok(
        [public(r) for r in records],
        "array",
        200,
        pagination={
            "limit": page["limit"],
            "offset": page["offset"],
            "total_count": total,
            "has_more": page["offset"] + len(records) < total,
        },
    )


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def pagination_params():
    """Lenient clamp to PRD bounds; bad values fall back to defaults."""
    try:
        limit = int(request.args.get("limit", PAGE_LIMIT_DEFAULT))
    except (TypeError, ValueError):
        limit = PAGE_LIMIT_DEFAULT
    try:
        offset = int(request.args.get("offset", PAGE_OFFSET_DEFAULT))
    except (TypeError, ValueError):
        offset = PAGE_OFFSET_DEFAULT
    limit = max(PAGE_LIMIT_MIN, min(PAGE_LIMIT_MAX, limit))
    offset = max(0, offset)
    return {"limit": limit, "offset": offset}


def body():
    """Parsed JSON body; absent/malformed body behaves as an empty object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
