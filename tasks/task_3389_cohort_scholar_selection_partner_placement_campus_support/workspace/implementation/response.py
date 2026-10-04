"""Standard response envelope (PRD 2.2).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}

The meta timestamp is a server wall-clock receipt stamp (PRD 2.2 example
predates the logical boot instant, so it is not the logical clock); entity
timestamps use the logical clock. Format matches: ISO 8601 UTC, 3 fractional
digits.
"""

import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

_ALNUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALNUM) for _ in range(20))


def _receipt_ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (n.microsecond // 1000)


def ok(data, status=200, pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _receipt_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def err(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _receipt_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
