"""Response envelope helpers.

Exact structure (SCAFFOLD.yaml section 1.0, PRD section 2.2):

  success: { "meta": { "api_request_id", "api_request_timestamp" [, limit,
             offset, total_count, has_more for list reads] },
             "response_type": "object" | "array",
             "data": {...} | [...] }

  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""

import random
import string
from datetime import datetime, timezone

_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def _now_iso():
    """ISO 8601 UTC with three fractional digits (PRD section 2.2)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _now_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    from flask import jsonify

    return jsonify({
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data,
    }), status


def success_object(data, status=200):
    return success(data, "object", status, None)


def success_array(items, limit, offset, total_count, status=200):
    return success(
        items,
        "array",
        status,
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
    )


def error_response(error_id, message, http_status):
    from flask import jsonify

    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status