"""Response envelope helpers (PRD section 2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(16))


def _stamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _stamp()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200, extra_meta=None):
    return jsonify({"meta": meta(extra_meta), "response_type": "object", "data": data}), status


def ok_array(items, limit, offset, total, status=200):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return jsonify({"meta": meta(extra), "response_type": "array", "data": items}), status


def error_body(error_id, message, status):
    return jsonify(
        {
            "meta": meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        }
    ), status
