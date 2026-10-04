"""Response envelope helpers — SCAFFOLD response_envelope / PRD 2.2.

Success:  {"meta": {"api_request_id", "api_request_timestamp"},
           "response_type": "object" | "array", "data": {...}}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id", "message"}}

List responses additionally carry limit/offset/total_count/has_more inside
`meta` (PRD 2.2, 2.3).  Error `meta` carries only the two identifiers.
"""

import random
import string
import time

import db

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(18))


def request_timestamp():
    """ISO 8601 UTC with three fractional digits, taken from real time.

    PRD 2.4 pins every *resource* timestamp to the logical clock; this
    envelope identifier is the server's own request metadata and is emitted
    from the process clock.
    """
    millis = int(time.time() * 1000) % 1000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".%03dZ" % millis


def meta(pagination=None):
    out = {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }
    if pagination is not None:
        out.update(pagination)
    return out


def ok(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    return {"meta": meta(pagination), "response_type": response_type, "data": data}, status


def no_content():
    """PRD section 4: a deletion returns 204 with no body at all.

    Returning a JSON body alongside 204 puts a Content-Length on a response
    that must carry no body, which desynchronizes keep-alive framing for the
    next request on the same connection.
    """
    return "", 204


def error(error_id, message, http_status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, http_status


# ---------------------------------------------------------------------------
# Pagination — limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def paginate(records, limit, offset):
    total = len(records)
    window = records[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


def read_pagination(params):
    """Parse limit/offset from query parameters, clamping and validating."""
    from errors import ApiError

    raw_limit = params.get("limit")
    raw_offset = params.get("offset")

    limit = 10
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")

    offset = 0
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")

    return limit, offset


def order_records(records):
    """PRD 2.3: list results order by created_at ascending."""
    return sorted(records, key=lambda r: (r.get("created_at") or "", r.get("_order", 0)))