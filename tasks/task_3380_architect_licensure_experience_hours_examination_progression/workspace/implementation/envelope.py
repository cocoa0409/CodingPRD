"""Response envelope helpers (PRD section 2.2) and pagination (section 2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail


def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": rid, "api_request_timestamp": ts}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    body["meta"]["limit"] = limit
    body["meta"]["offset"] = offset
    body["meta"]["total_count"] = total_count
    body["meta"]["has_more"] = (offset + len(items)) < total_count
    return jsonify(body), 200


def err(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def pagination_params():
    """limit defaults to 10, must be 1..100; offset defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit and offset must be integers")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, sort_key=None):
    """Sort (default: created_at ascending, stable over insertion order) and
    apply the limit/offset window."""
    limit, offset = pagination_params()
    if sort_key is None:
        ordered = sorted(records, key=lambda r: r.get("created_at", ""))
    else:
        ordered = sorted(records, key=sort_key)
    total = len(ordered)
    return ok_list(ordered[offset:offset + limit], total, limit, offset)
