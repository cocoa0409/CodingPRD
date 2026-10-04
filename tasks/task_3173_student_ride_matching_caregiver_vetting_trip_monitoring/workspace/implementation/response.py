"""Response envelope helpers.

Transcribed from SCAFFOLD.yaml section 1.0 and PRD section 2.2/2.3:
    { "meta": { "api_request_id", "api_request_timestamp" ... pagination },
      "response_type": "object" | "array",
      "data": ... }
Errors use response_type "error" and a data body of { error_id, message }.
"""

from clock import fmt_dt, new_request_id, now_utc

PAGINATION_FIELDS = ("limit", "offset", "total_count", "has_more")
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_utc()),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return body, status


def array_response(items, limit=None, offset=None, total_count=None, status=200):
    """Build a list envelope.

    PRD section 2.3: paged AND non-paged list responses alike report limit,
    offset, total_count and has_more. A non-paged response (a returned Trip[],
    GeofenceCheck[], RideRequest[]...) reports the whole set, so its limit is the
    size of that set.
    """
    meta = _meta()
    if limit is None:
        limit = len(items) if items else DEFAULT_LIMIT
        offset = 0
        total_count = len(items)
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return body, status


def empty_response(status=200):
    """2xx with no data carries an empty object (PRD section 2.2)."""
    return object_response({}, status)


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, status


def paginate(items, args):
    """Apply limit/offset from query args.

    Returns (page_items, limit, offset, total_count). Defaults, min and max come
    from response_envelope.pagination_defaults (limit 10, min 1, max 100, offset 0).
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    try:
        offset = int(raw_offset) if raw_offset not in (None, "") else DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    total = len(items)
    return items[offset:offset + limit], limit, offset, total