"""Response envelope helpers per PRD 2.2/2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _req_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _now_ts():
    dt = datetime.now(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return ms


def meta(include_pagination=False, limit=None, offset=None, total=None, has_more=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": _now_ts(),
    }
    if include_pagination:
        m["limit"] = limit
        m["offset"] = offset
        m["total_count"] = total
        m["has_more"] = has_more
    return m


def ok(data, status=200, include_pagination=False, limit=None, offset=None, total=None):
    body = {
        "meta": meta(include_pagination, limit, offset, total,
                    (offset + len(data)) < total if include_pagination else None),
        "response_type": "array" if include_pagination else "object",
        "data": data,
    }
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
