"""Response envelope, entity helpers, pagination."""
import uuid

from flask import g, jsonify, request

import store
from clock import now_iso3
from errors import raise_err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso3(),
    }


def ok_obj(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def ok_list(items, limit, offset, total):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def err_response(error_id, status, message):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status


def new_entity(fields):
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso3(),
        "updated_at": now_iso3(),
        "version": 1,
        "_seq": store.next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    """Record a mutation of a resource: refresh updated_at and bump version.

    A resource's version increments at most once per request, no matter how
    many transitions/cascades touch it within that request.
    """
    bumped = getattr(g, "_bumped", None)
    if bumped is None:
        e["version"] += 1
        e["updated_at"] = now_iso3()
        return
    if id(e) not in bumped:
        e["version"] += 1
        e["updated_at"] = now_iso3()
        bumped.add(id(e))


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _parse_int_param(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "%s must be an integer" % name)


def paginate(items):
    """Apply limit/offset query params; returns (page, limit, offset, total)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    return items[offset:offset + limit], limit, offset, total
