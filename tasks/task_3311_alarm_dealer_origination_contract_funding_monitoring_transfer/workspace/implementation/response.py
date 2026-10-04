"""Response envelope helpers.

Shapes are read verbatim from SCAFFOLD §1.0 response_envelope (and PRD §2.2):
success -> { meta: {...}, response_type: "object"|"array", data: {} }
error   -> { meta: {...}, response_type: "error", data: { error_id, message } }
Pagination fields sit in `meta`: limit, offset, total_count, has_more.
"""

import random
import string
from datetime import timezone

import db
from util import fmt_ts

# SCAFFOLD §1.0 pagination_defaults
PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def new_request_id():
    suffix = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(15))
    return "req_" + suffix


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(db.now().astimezone(timezone.utc)),
    }


def envelope_object(data):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return body


def envelope_array(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    return {"meta": meta, "response_type": "array", "data": rows}


def envelope_error(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def paginate(rows, limit, offset):
    """Grab the page and report the filtered total."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def resolve_pagination(query):
    """Read ?limit/?offset with the scaffold's defaults; clamp to the declared bounds."""
    limit_raw = query.get("limit")
    offset_raw = query.get("offset")
    limit = PAGINATION_DEFAULTS["limit"]
    offset = PAGINATION_DEFAULTS["offset"]
    if limit_raw is not None and str(limit_raw) != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = PAGINATION_DEFAULTS["limit"]
    if offset_raw is not None and str(offset_raw) != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = PAGINATION_DEFAULTS["offset"]
    if limit < PAGINATION_DEFAULTS["min"]:
        limit = PAGINATION_DEFAULTS["min"]
    if limit > PAGINATION_DEFAULTS["max"]:
        limit = PAGINATION_DEFAULTS["max"]
    if offset < 0:
        offset = 0
    return limit, offset