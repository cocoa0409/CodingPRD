"""The fixed response envelope (SCAFFOLD.yaml §1.0, PRD §2.2).

Success:
  { "meta": { "api_request_id": "req_...", "api_request_timestamp": "ISO8601" },
    "response_type": "object" | "array", "data": {} }
Error:
  { "meta": {...}, "response_type": "error",
    "data": { "error_id": "ERR_XXX", "message": "..." } }

List responses additionally carry the pagination fields in `meta`.
"""

import random
import string

from apptime import fmt, now_dt

_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id() -> str:
    suffix = "".join(random.choice(_ALPHANUM) for _ in range(18))
    return "req_" + suffix


def _meta(pagination: dict = None) -> dict:
    meta = {
        "api_request_id": new_request_id(),
        # Server-generated: the clock's instant to millisecond precision.
        "api_request_timestamp": fmt(now_dt()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, response_type: str = "object", pagination: dict = None) -> dict:
    return {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": {} if data is None else data,
    }


def array(items, pagination: dict) -> dict:
    return success(items, response_type="array", pagination=pagination)


def error(error_id: str, message: str) -> dict:
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }