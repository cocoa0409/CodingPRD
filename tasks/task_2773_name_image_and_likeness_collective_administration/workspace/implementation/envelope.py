"""The response envelope of PRD 2.2 and the pagination contract of PRD 2.3."""

import random
import string
from datetime import datetime, timezone

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def object_response(data, status=200):
    return {"meta": _meta(), "response_type": "object", "data": data or {}}, status


def list_response(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    return {"meta": meta, "response_type": "array", "data": page}, 200


def error_response(error_id, message, status):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }, status


def read_pagination(args):
    """limit default 10 / min 1 / max 100; offset default 0 / min 0."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        limit = _int_param(raw_limit, "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        offset = _int_param(raw_offset, "offset")
        if offset < OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def _int_param(raw, name):
    text = str(raw).strip()
    negative = text.startswith("-")
    body = text[1:] if (negative or text.startswith("+")) else text
    if not body.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(body)
    return -value if negative else value


def enum_filter(args, name, allowed):
    """A declared enum filter must carry a declared value (PRD 2.8 priority 5)."""
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a recognised value for %s." % (raw, name))
    return raw


def id_filter(args, name):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    return raw
