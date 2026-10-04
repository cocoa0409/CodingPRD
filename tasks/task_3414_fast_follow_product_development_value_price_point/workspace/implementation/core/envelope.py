"""Response envelope helpers (PRD 2.2).

Success: {meta: {api_request_id, api_request_timestamp, [pagination]},
          response_type: "object" | "array", data: ...}
Error:   {meta: {api_request_id, api_request_timestamp},
          response_type: "error", data: {error_id, message}}

Pagination fields (limit, offset, total_count, has_more) appear in meta only
for list endpoints.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from core import clock


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": clock.wallclock_now_iso(),
    }


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    return jsonify(body), api_err.status


def pub(rec):
    """Serialize a stored record: drop underscore-prefixed internal fields,
    render datetimes per PRD 2.4/2.5 — created_at/updated_at with three
    fractional digits, every other datetime as the logical-clock instant
    string — and convert Decimals to floats."""
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            if key in ("created_at", "updated_at"):
                out[key] = clock.fmt(value)
            else:
                out[key] = clock.fmt_instant(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out
