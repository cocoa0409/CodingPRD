"""Response envelope helpers.

Envelope shapes are taken verbatim from SCAFFOLD.yaml §1.0 / PRD.md §2.2:

  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object" | "array", "data": ... }
  error:   { "meta": {...}, "response_type": "error",
             "data": {"error_id": ..., "message": ...} }

pagination_fields: limit, offset, total_count, has_more
pagination_defaults: limit 10 (min 1, max 100), offset 0
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def now_iso():
    """Server-generated ISO 8601 UTC timestamp with three fractional digits.

    This is a wall-clock stamp for the envelope's api_request_timestamp; the
    *logical* clock (app.clock) governs every business-temporal rule.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(random.choice(alphabet) for _ in range(12))
    return "req_" + body


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return meta


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_array(items, limit, offset, total_count, code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    return jsonify(
        {"meta": _meta(pagination), "response_type": "array", "data": items}
    ), code


def error_body(error_id, message, http_status):
    return jsonify(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        }
    ), http_status


# --- pagination helpers -------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def read_pagination(args):
    """Read limit/offset per response_envelope.pagination_defaults.

    Invalid (non-integer) values fall back to the defaults rather than raising,
    since the scaffold declares no error for them.
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit not in (None, "") else LIMIT_DEFAULT
    except (TypeError, ValueError):
        limit = LIMIT_DEFAULT
    try:
        offset = int(raw_offset) if raw_offset not in (None, "") else OFFSET_DEFAULT
    except (TypeError, ValueError):
        offset = OFFSET_DEFAULT
    if limit < LIMIT_MIN:
        limit = LIMIT_MIN
    if limit > LIMIT_MAX:
        limit = LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, limit, offset, total