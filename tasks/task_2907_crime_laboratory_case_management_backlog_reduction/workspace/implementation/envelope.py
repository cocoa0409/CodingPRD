"""Response envelope and pagination (PRD sections 2.2, 2.3)."""
import json
import random
import string
from datetime import datetime, timezone

from flask import Response, request

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
    moment = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def _emit(body, status):
    return Response(
        json.dumps(body, allow_nan=False),
        status=status,
        mimetype="application/json",
    )


def object_response(data, status=200):
    return _emit(
        {"meta": base_meta(), "response_type": "object", "data": data},
        status,
    )


def array_response(rows, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return _emit(
        {"meta": meta, "response_type": "array", "data": rows},
        200,
    )


def error_response(error_id, message, status):
    return _emit(
        {
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


def _positive_int(raw, name):
    text = raw.strip()
    if text == "" or not (text.isdigit() or (text[0] == "-" and text[1:].isdigit())):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be an integer." % name,
        )
    return int(text)


def pagination():
    """limit/offset from the query string, validated per PRD section 2.3."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _positive_int(raw_limit, "limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Query parameter 'limit' must be between %d and %d."
                % (LIMIT_MIN, LIMIT_MAX),
            )
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _positive_int(raw_offset, "offset")
        if offset < OFFSET_MIN:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Query parameter 'offset' must be at least %d." % OFFSET_MIN,
            )
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
