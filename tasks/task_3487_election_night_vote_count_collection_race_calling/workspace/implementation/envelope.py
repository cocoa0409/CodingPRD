"""Response envelope (SCAFFOLD §1.0 / PRD §2.2) and pagination (PRD §2.3)."""
import uuid

from flask import jsonify, request

from clock import now as clock_now
from util import fmt_dt
from errors import raise_err

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_dt(clock_now()),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
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


def parse_pagination():
    """limit/offset per PRD §2.3: default 10/0, limit in [1,100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise_err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if raw_offset is None:
        offset = PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records, serialize=None):
    """Sort by (created_at, _seq) ascending — the default list order of PRD
    §2.3 — then slice. `serialize` maps a record to its JSON form."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    if serialize is not None:
        page = [serialize(r) for r in page]
    return ok_list(page, limit, offset, total)
