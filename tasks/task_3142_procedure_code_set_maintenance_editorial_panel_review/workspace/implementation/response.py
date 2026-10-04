"""Response envelope helpers.

Envelope shape is taken verbatim from PRD.md section 2.2 and from
SCAFFOLD.yaml `response_envelope`:

    { "meta": { "api_request_id", "api_request_timestamp", ...pagination },
      "response_type": "object" | "array" | "error",
      "data": { ... } }

Pagination field names and defaults come from
`response_envelope.pagination_fields` / `pagination_defaults`:
limit (default 10, min 1, max 100), offset (default 0), total_count, has_more.
"""

import uuid

from flask import jsonify

from errors import ERR_INVALID_STATE, ApiError

API_PREFIX = "/cpt"

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Maximum precision any stored datetime is rendered at.
_TS_PRECISION = 3


def request_id():
    """Server-generated unique request identifier prefixed with `req_`."""
    return "req_" + uuid.uuid4().hex[:16].upper()


def format_ts(value):
    """Render a stored datetime as ISO 8601 UTC with 3 fractional digits."""
    if value is None:
        return None
    return value.isoformat(timespec="microseconds").rstrip("0").rstrip(".")

def _render_ts(value):
    if value is None:
        return None
    text = value.isoformat(timespec="microseconds")
    date_part, time_part = text.split("T")
    fraction = time_part.split("+")[0].split("-")[0]
    if "." in fraction:
        whole, frac = fraction.split(".")
    else:
        whole, frac = fraction, ""
    frac = (frac + "000")[:_TS_PRECISION]
    return date_part + "T" + whole + "." + frac + "Z"


def envelope(data, response_type="object", status=200, meta_extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": _render_ts(_now()),
    }
    if meta_extra:
        meta.update(meta_extra)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def object_response(data, status=200):
    return envelope(data, "object", status)


def array_response(rows, limit, offset, total_count):
    has_more = (offset + len(rows)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return envelope(rows, "array", 200, meta_extra)


def error_response(error_id, message, status=None):
    from errors import HTTP_STATUS

    code = status or HTTP_STATUS.get(error_id, 400)
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": _render_ts(_now()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), code


def _now():
    from clock import logical_now

    return logical_now()


def parse_pagination(args):
    """Read `limit` / `offset`; out-of-range limit is rejected, not clamped.

    PRD.md 2.3: "it may not be lower than 1 and may not exceed 100, and a value
    outside that range is rejected rather than clamped."  The catalogue carries
    no identifier specific to a malformed pagination control, so the rejection
    is reported through the catalogued identifier for a request that is not
    admissible.
    """
    raw_limit = args.get("limit")
    if raw_limit is None or raw_limit == "":
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_STATE, "malformed limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(ERR_INVALID_STATE, "limit outside the permitted range")

    raw_offset = args.get("offset")
    if raw_offset is None or raw_offset == "":
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = PAGINATION_DEFAULT_OFFSET
        if offset < 0:
            offset = PAGINATION_DEFAULT_OFFSET
    return limit, offset


def paginate(rows, limit, offset):
    """Return (window, full matching count); oldest-first ordering is the
    caller's responsibility because some endpoints override the sort."""
    total_count = len(rows)
    return rows[offset:offset + limit], total_count