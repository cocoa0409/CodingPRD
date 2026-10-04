"""Response envelope helpers (PRD 2.2).

Success:
    { "meta": { "api_request_id", "api_request_timestamp",
                ["limit","offset","total_count","has_more"] },
      "response_type": "object"|"array", "data": {...} | [...] }

Error:
    { "meta": { "api_request_id", "api_request_timestamp" },
      "response_type": "error",
      "data": { "error_id": ..., "message": ... } }
"""

from flask import g, jsonify

from util import fmt_ts
import errors as E
from store import store


def _meta(extra=None):
    meta = {
        "api_request_id": g.get("request_id") or store.request_id(),
        "api_request_timestamp": fmt_ts(store.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200, pagination=None):
    return jsonify({
        "meta": _meta(pagination),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def array_response(items, limit, offset, total_count, status=200):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), status


def error_response(error_id, message, status=None):
    if status is None:
        status = E.ERROR_STATUS.get(error_id, 400)
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message or error_id},
    }), status


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def sort_by_created(records):
    """PRD 2.3: ascending created_at, oldest first."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_order", 0)))