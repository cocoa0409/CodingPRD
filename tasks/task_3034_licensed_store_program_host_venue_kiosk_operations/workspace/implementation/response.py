"""Response envelope helpers (SCAFFOLD response_envelope + PRD §2.2)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}
    if extra:
        m.update(extra)
    return m


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {"meta": _meta(extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def success_no_content():
    return "", 204


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
