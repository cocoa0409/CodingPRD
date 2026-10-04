"""Standard response envelope helpers.

Every response follows PRD section 2.2 / SCAFFOLD section 1.0:
  success: { "meta": {...}, "response_type": "object"|"array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id", "message" } }
Pagination fields (limit/offset/total_count/has_more) live in `meta` and are
only present for list endpoints.
"""

import random
import string
from datetime import datetime, timezone


def timestamp_now():
    """ISO 8601 UTC with exactly three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def request_id():
    alphabet = string.ascii_letters + string.digits
    body = "".join(random.choice(alphabet) for _ in range(18))
    return "req_" + body


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": timestamp_now(),
    }


def success(data, response_type="object"):
    return {"meta": _meta(), "response_type": response_type, "data": data}


def success_object(data):
    return success(data, "object")


def success_array(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {"meta": meta, "response_type": "array", "data": items}


def error(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }