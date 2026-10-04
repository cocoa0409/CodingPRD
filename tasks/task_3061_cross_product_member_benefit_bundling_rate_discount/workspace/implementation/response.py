"""Standard response envelope helpers (PRD section 2.2)."""

from flask import jsonify

from db import DB
from timeutil import fmt_ts


def _meta(pagination=None):
    meta = {
        "api_request_id": DB.next_request_id(),
        "api_request_timestamp": fmt_ts(DB.clock()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok_object(data):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data})


def ok_array(items, limit=None, offset=None, total_count=None):
    offset = offset or 0
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count if total_count is not None else False,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items})


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }