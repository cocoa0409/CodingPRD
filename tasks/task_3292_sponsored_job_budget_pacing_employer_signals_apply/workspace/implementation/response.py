"""Response envelope helpers — field names taken verbatim from response_envelope."""

import random
import string
import time
from datetime import datetime, timezone

from flask import jsonify

ALPHANUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(22))


def wall_now():
    return datetime.now(timezone.utc)


def _stamp(dt=None):
    dt = dt or wall_now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": _stamp()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, page=None):
    body = {"meta": meta(page), "response_type": "object", "data": data}
    return jsonify(body), status


def array(items, status=200, page=None):
    body = {"meta": meta(page), "response_type": "array", "data": items}
    return jsonify(body), status


def err(error_id, message):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), 0  # status is filled in by the caller


def error_response(error_id, message, http_status):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status


def page_meta(limit, offset, total_count):
    has_more = (offset + limit) < total_count
    return {"limit": limit, "offset": offset, "total_count": total_count, "has_more": has_more}


def paginate(items, limit, offset):
    return items[offset:offset + limit]