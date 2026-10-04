"""Standard response envelope (PRD §2.2).

    success: { "meta": { "api_request_id", "api_request_timestamp", ... },
               "response_type": "object" | "array", "data": ... }
    error:   { "meta": { "api_request_id", "api_request_timestamp" },
               "response_type": "error",
               "data": { "error_id", "message" } }

Pagination fields (`limit`, `offset`, `total_count`, `has_more`) are added to
`meta` for list responses only (PRD §2.3).
"""
import random
import string
from datetime import datetime, timezone

_ALNUM = string.ascii_uppercase + string.digits


def iso8601_now() -> str:
    """ISO 8601 UTC instant with three fractional digits (PRD §2.2)."""
    return (
        datetime.now(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z"
    )


def new_request_id() -> str:
    suffix = "".join(random.choices(_ALNUM, k=18))
    return "req_" + suffix


def _meta(extra=None) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso8601_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def success_array(items, limit, offset, total_count):
    extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return {"meta": _meta(extra), "response_type": "array", "data": items}