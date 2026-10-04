"""Standard response envelope helpers (PRD 2.2)."""

import random
import string
from datetime import timezone

from flask import jsonify

import db

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def _timestamp():
    instant = db.now()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def meta(extra=None):
    base = {"api_request_id": request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        base.update(extra)
    return base


def ok(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total_count):
    payload = {
        "meta": meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(payload), 200


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, http_status):
    return jsonify(error_body(error_id, message)), http_status