"""Response envelope helpers per scaffold response_envelope."""
import uuid
from datetime import timezone
from flask import jsonify

from db import db


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(round(dt.microsecond / 1000.0))
    if ms >= 1000:
        ms = 999
    return f"{base}.{ms:03d}Z"


def now_iso():
    return fmt_ts(db.clock.now())


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_ts(db.clock.current()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_ts(db.clock.current()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": fmt_ts(db.clock.current()),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status
