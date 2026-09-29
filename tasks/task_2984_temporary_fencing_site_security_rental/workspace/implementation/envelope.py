"""The response envelope of PRD 2.2."""

import random
import string
from datetime import datetime, timezone

from validation import iso_ms

_ALNUM = string.ascii_uppercase + string.digits


def request_meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    return {"meta": request_meta(), "response_type": "object", "data": data or {}}, status


def list_response(items, limit, offset, total_count):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def error_response(error_id, message, status):
    return {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }, status


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
