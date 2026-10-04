"""Response envelope helpers.

The envelope is FIXED by SCAFFOLD.yaml `response_envelope` and PRD.md §2.2:

  success: { "meta": {...}, "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": ..., "message": ... } }

Pagination fields (`limit`, `offset`, `total_count`, `has_more`) live inside
`meta` and are added only for list responses.
"""

import random
import string

from errors import ApiError

_ALPHANUM = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _meta(clock, extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.stamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, clock):
    """Single-resource success body."""
    return {"meta": _meta(clock), "response_type": "object", "data": data}


def ok_empty(clock):
    """Success body with no payload — data is an empty object."""
    return {"meta": _meta(clock), "response_type": "object", "data": {}}


def ok_list(items, clock, limit, offset, total_count):
    """List success body: pagination fields ride inside `meta`."""
    return {
        "meta": _meta(clock, {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + limit) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }


def error_body(err, clock):
    return {
        "meta": _meta(clock),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


__all__ = ["ApiError", "ok", "ok_empty", "ok_list", "error_body"]