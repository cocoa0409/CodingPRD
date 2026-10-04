"""Response envelope helpers (PRD section 2.2 / SCAFFOLD response_envelope)."""
import uuid
from datetime import datetime, timezone

from flask import jsonify


def _wall_ts():
    """meta.api_request_timestamp: server wall clock, ISO 8601 UTC, 3 frac digits."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": _wall_ts(),
    }


def ok(data, response_type="object", status=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def paginate(items, limit, offset):
    """Slice a pre-sorted list; returns (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
