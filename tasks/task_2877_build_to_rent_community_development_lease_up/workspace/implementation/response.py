"""Standard response envelopes (PRD section 2.2) and pagination (PRD section 2.3)."""
from __future__ import annotations

import random
import string
from datetime import datetime, timezone

from db import commit
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


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


def object_envelope(data, status=200):
    return {
        "meta": base_meta(),
        "response_type": "object",
        "data": data,
    }, status


def array_envelope(items, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(items) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }, status


def error_envelope(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------- handler helpers
def ok(serializer, record):
    """200 with a single serialized resource; commits pending version bumps first."""
    commit()
    return object_envelope(serializer(record), 200)


def ok_data(data):
    commit()
    return object_envelope(data, 200)


def created(serializer, record):
    """201 with a single serialized resource; commits pending version bumps first."""
    commit()
    return object_envelope(serializer(record), 201)


def listing(serializer, records, limit, offset):
    total_count = len(records)
    window = records[offset:offset + limit]
    commit()
    return array_envelope([serializer(item) for item in window], limit, offset, total_count)


def page_params(args):
    """limit / offset from the query string, validated against PRD section 2.3 bounds."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        limit = _positive_int(raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        offset = _positive_int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative")
    return limit, offset


def _positive_int(raw):
    text = str(raw).strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "pagination parameters must be integers")
