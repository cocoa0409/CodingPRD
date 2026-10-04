"""Standard response envelope helpers (PRD 2.2) and pagination (PRD 2.3)."""
from datetime import datetime, timezone

from flask import jsonify

import db
from errors import err


def _meta():
    # The request timestamp is server-generated wall time with 3 fractional
    # digits (it is metadata, not the logical clock).
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"
    return {"api_request_id": db.request_id(), "api_request_timestamp": ts}


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status


def parse_pagination(args):
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = 0 if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, args):
    """Apply filters-sorted-by-creation + pagination; records already filtered."""
    limit, offset = parse_pagination(args)
    ordered = sorted(records, key=lambda r: (r["_seq"],))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([db.public(r) for r in page], total, limit, offset)
