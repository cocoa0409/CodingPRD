"""Response envelope helpers.

The envelope is fixed by PRD §2.2 and SCAFFOLD §1.0:

    { "meta": {...}, "response_type": "object"|"array"|"error", "data": ... }

Success responses carry only api_request_id and api_request_timestamp inside
meta (list responses add limit/offset/total_count/has_more); error responses
carry only the two identifiers plus an error_id/message data object.
"""

import random
import string
from datetime import datetime, timezone

from db import STORE, now

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def _timestamp():
    dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def read_pagination(args):
    """Read limit/offset from the query string using the scaffold defaults."""
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None and str(raw_limit).strip() != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
    raw_offset = args.get("offset")
    if raw_offset is not None and str(raw_offset).strip() != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = DEFAULT_OFFSET
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def success(data, status=200, pagination=None):
    if pagination is None:
        response_type = "array" if isinstance(data, list) else "object"
        body = {"meta": _meta(), "response_type": response_type, "data": data}
    else:
        body = {"meta": _meta(pagination), "response_type": "array", "data": data}
    return body, status


def success_list(items, limit, offset, status=200):
    window, pagination = paginate(items, limit, offset)
    return success(window, status=status, pagination=pagination)


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, http_status


def created(data):
    return success(data, status=201)