"""Response envelope construction (scaffold response_envelope / PRD section 2.2).

Success:
    { "meta": {...}, "response_type": "object"|"array", "data": ... }
Error:
    { "meta": {...}, "response_type": "error", "data": {error_id, message} }

List responses add limit / offset / total_count / has_more to ``meta``.
"""

import random
import string
from datetime import datetime, timezone

_ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(12))


def real_now_iso3():
    """ISO 8601 UTC with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    return "%s.%03dZ" % (now.strftime("%Y-%m-%dT%H:%M:%S"), now.microsecond // 1000)


def _base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": real_now_iso3(),
    }


def success(data, response_type=None, pagination=None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    meta = _base_meta()
    if pagination is not None:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}


def error(error_id, message):
    return {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_meta(limit, offset, total_count):
    return {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }