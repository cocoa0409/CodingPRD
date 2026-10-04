"""Response envelope helpers — envelope shape read from SCAFFOLD.yaml §1.5
`response_envelope` and PRD.md §2.2/§2.3."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def api_request_id():
    body = "".join(random.choices(string.ascii_uppercase + string.digits, k=18))
    return "req_" + body


def api_request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": api_request_id(),
        "api_request_timestamp": api_request_timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status=200, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_array(items, limit, offset, total_count, status=200):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status