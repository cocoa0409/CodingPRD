"""Response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify

import clock

_ALPHANUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.fmt_instant(clock.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def empty(status=200):
    return obj({}, status)


def collection(rows, limit, offset, total_count, status=200):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(rows)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), status


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
