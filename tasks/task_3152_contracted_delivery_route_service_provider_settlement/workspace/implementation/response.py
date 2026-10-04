"""Standard response envelope (SCAFFOLD §response_envelope, PRD §2.2)."""

import random
import string

from db import iso_now, db, COMMON_FIELD_TYPES
from errors import ApiError

_ALPHANUM = string.ascii_uppercase + string.digits

# Query-param key -> envelope meta key, for the four pagination fields.
PAGINATION_QUERY_FIELDS = {"limit": "limit", "offset": "offset"}
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(16))


def meta_base():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso_now(db.clock),
    }


def success(data, response_type="object", pagination=None, status=200):
    from flask import jsonify

    meta = meta_base()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_body(err):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


def entity_payload(entity_type, row):
    """Serialize a row for a response body.

    Common-field rows expose `id`/`created_at`/`updated_at`/`version` plus their
    own declared fields. The three bare resources expose only `id`/`created_at`.
    """
    payload = dict(row)
    payload.pop("__type", None)
    payload.pop("_seq", None)
    # Internal `*_dt` mirrors of the declared timestamps never surface in a body.
    for key in [k for k in payload if k.endswith("_dt")]:
        payload.pop(key, None)
    if entity_type not in COMMON_FIELD_TYPES:
        payload.pop("updated_at", None)
        payload.pop("version", None)
    if entity_type == "ServiceProvider":
        # brand_compliance_pct is derived; it may legitimately be 0.00 with no fleet.
        if payload.get("brand_compliance_pct") is None:
            payload["brand_compliance_pct"] = 0.00
    return payload


def paginate(items, args):
    """Slice a list by the scaffold's pagination parameters.

    `limit` defaults to 10, clamped into [1, 100]; `offset` defaults to 0.
    Returns (page_items, pagination_meta_dict).
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }