"""Response envelope helpers.

SCAFFOLD response_envelope (fixed, emitted verbatim):

  success: { "meta": { "api_request_id": ..., "api_request_timestamp": ... },
             "response_type": "object" | "array", "data": {} }
  error:   { "meta": {...}, "response_type": "error",
             "data": { "error_id": ..., "message": ... } }

List responses additionally carry limit / offset / total_count / has_more in
meta (PRD 2.3).
"""

import random
import string

from constants import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
    fmt_dt,
)
import db
from errors import ApiError, ERR_INVALID_REQUEST


_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def timestamp():
    # Server-generated ISO 8601 UTC with three fractional digits.  Derived from
    # the logical clock so it is stable and never wall-clock dependent.
    return fmt_dt(db.STORE.now())


def _meta(extra=None):
    meta = {"api_request_id": request_id(), "api_request_timestamp": timestamp()}
    if extra:
        meta.update(extra)
    return meta


def ok_object(data):
    return {"meta": _meta(), "response_type": "object", "data": data}


def ok_array(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return {"meta": _meta(meta_extra), "response_type": "array", "data": items}


def error_body(err, status):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


def pagination_args(args):
    """Read limit/offset from the query string with the scaffold's defaults,
    minimum and maximum.  Out-of-range or non-integer values are a malformed
    request (ERR_INVALID_REQUEST)."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "limit must be between %d and %d" % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX),
            )

    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items, args):
    """Slice an already-sorted list and build the array envelope."""
    limit, offset = pagination_args(args)
    total_count = len(items)
    page = items[offset:offset + limit]
    return ok_array(page, limit, offset, total_count)