"""Standard response envelope (PRD 2.2, verbatim structure)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(16))


def now_iso_utc():
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso_utc(),
    }


def ok(data, response_type="object", status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def created(data):
    return ok(data, "object", 201)


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def page(rows, limit, offset, total_count):
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(rows) < total_count,
    }
    return ok(rows, "array", 200, pagination=meta)