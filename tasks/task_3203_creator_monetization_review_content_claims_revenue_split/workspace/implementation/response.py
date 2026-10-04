"""Standard response envelope helpers (SCAFFOLD section 1.0 / PRD section 2.2)."""

import random
import string

from flask import jsonify

from db import now, to_iso8601

_ALPHANUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": to_iso8601(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_array(rows, limit, offset, total_count):
    body = {
        "meta": _meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + len(rows)) < total_count,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def ok_empty(pagination=None):
    body = {"meta": _meta(pagination), "response_type": "object", "data": {}}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }