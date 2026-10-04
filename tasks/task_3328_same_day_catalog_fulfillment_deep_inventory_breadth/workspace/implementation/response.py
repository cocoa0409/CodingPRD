"""Standard response envelope helpers.

Envelope shape (SCAFFOLD.yaml section 1.0, PRD section 2.2):

    { "meta": {"api_request_id": "req_...", "api_request_timestamp": "ISO8601"},
      "response_type": "object" | "array" | "error",
      "data": ... }

List responses additionally carry limit / offset / total_count / has_more in
`meta`. Error responses carry `meta` with only the two request fields.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status