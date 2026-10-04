"""Standard response envelope helpers."""

import random
import string

from db import format_wall_clock

_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _meta(limit=None, offset=None, total_count=None, has_more=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": format_wall_clock(),
    }
    if limit is not None:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total_count
        meta["has_more"] = has_more
    return meta


def object_response(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def array_response(items, limit, offset, total_count):
    return {
        "meta": _meta(limit=limit, offset=offset, total_count=total_count,
                      has_more=(offset + len(items)) < total_count),
        "response_type": "array",
        "data": items,
    }


def error_response(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }