"""Response envelope helpers implementing PRD 2.2 exactly.

Success: {"meta": {api_request_id, api_request_timestamp}, "response_type": "object"|"array", "data": ...}
List responses add limit/offset/total_count/has_more inside meta (PRD 2.3).
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
The meta timestamp is server-generated ISO 8601 UTC with three fractional
digits; it reads the logical clock like every other timestamp in the system.
"""

import secrets

from flask import jsonify

import db


def _meta(extra=None):
    m = {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": db.now_iso(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def listing(items, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error(err):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )
