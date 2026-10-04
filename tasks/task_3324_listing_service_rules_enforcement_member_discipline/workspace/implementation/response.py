"""Standard response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""

import secrets
import string
from flask import jsonify

from db import _fmt_iso, now as clock_now


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        # Use the logical clock for the envelope timestamp so that responses are
        # reproducible from recorded state; PRD only requires ISO8601 UTC with
        # three fractional digits.
        "api_request_timestamp": _fmt_iso(clock_now()),
    }
    if extra:
        m.update(extra)
    return m


def success_object(data, http_status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
