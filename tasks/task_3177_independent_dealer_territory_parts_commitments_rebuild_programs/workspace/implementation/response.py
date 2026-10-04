"""Standard response envelope helpers.

The envelope is emitted verbatim per SCAFFOLD §1.0:

    { "meta": {...}, "response_type": "object"|"array"|"error", "data": {...} }
"""

from __future__ import annotations

import random
import string
from datetime import datetime, timezone

_ALPHANUM = string.ascii_letters + string.digits


def request_id() -> str:
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def request_timestamp() -> str:
    value = datetime.now(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:23] + "Z"


def _meta() -> dict:
    return {"api_request_id": request_id(), "api_request_timestamp": request_timestamp()}


def ok(data, response_type: str = "object") -> dict:
    return {"meta": _meta(), "response_type": response_type, "data": data}


def paged(items: list, limit: int, offset: int, total_count: int) -> dict:
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {"meta": meta, "response_type": "array", "data": items}


def failure(error_id: str, message: str) -> dict:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }