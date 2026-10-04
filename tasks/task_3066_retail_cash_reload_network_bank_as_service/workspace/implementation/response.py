"""Response envelope.

The envelope is emitted verbatim per the scaffold's response_envelope section
and PRD 2.2:

    { "meta": { "api_request_id": "req_xxx", "api_request_timestamp": "ISO8601" },
      "response_type": "object" | "array", "data": {} }

List responses additionally carry limit / offset / total_count / has_more in
meta.
"""

import random
import string

from flask import jsonify

import timeutil

# Pagination parameter names and defaults, read from response_envelope.
PAGINATION_FIELDS = ("limit", "offset", "total_count", "has_more")
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(18))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": timeutil.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def array(items, limit, offset, total_count):
    return (
        jsonify(
            {
                "meta": _meta(
                    {
                        "limit": limit,
                        "offset": offset,
                        "total_count": total_count,
                        "has_more": (offset + len(items)) < total_count,
                    }
                ),
                "response_type": "array",
                "data": items,
            }
        ),
        200,
    )


def error(error_id, message, status):
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