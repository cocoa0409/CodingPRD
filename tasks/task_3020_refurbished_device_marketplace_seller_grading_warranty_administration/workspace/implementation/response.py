"""Standard response envelope helpers.

Success:  {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...}}
List responses carry limit/offset/total_count/has_more inside `meta`.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_META = ("api_request_id", "api_request_timestamp")


def _request_id():
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=15))
    return "req_" + tail


def _timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(extra=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status