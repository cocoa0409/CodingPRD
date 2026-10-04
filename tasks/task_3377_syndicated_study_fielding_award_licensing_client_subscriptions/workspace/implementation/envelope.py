"""Response envelope helpers — exact structure from PRD section 2.2/2.3."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from timeutil import iso3


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso3(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginated(records, serializer):
    """Sort by created_at ascending (stable via insertion seq) and paginate."""
    from validation import parse_limit_offset

    limit, offset = parse_limit_offset()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


def filter_params(items, params):
    """Apply exact-match query filters for the named fields."""
    out = items
    for param in params:
        v = request.args.get(param)
        if v is not None:
            out = [r for r in out if r.get(param) == v]
    return out
