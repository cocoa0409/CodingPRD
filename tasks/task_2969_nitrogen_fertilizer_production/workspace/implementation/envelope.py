"""The response envelope of PRD 2.2, plus the pagination window of PRD 2.3."""
import random
import string

from flask import jsonify

from errors import ApiError
from store import db
from util import fmt_dt

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(db.clock),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def list_response(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paging(args):
    """Parse limit/offset. Anything outside the declared bounds is a 422."""
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None or limit == "":
        limit_v = 10
    else:
        limit_v = _int_param(limit, "limit")
        if limit_v < 1 or limit_v > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_v = 0
    else:
        offset_v = _int_param(offset, "offset")
        if offset_v < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit_v, offset_v


def _int_param(raw, name):
    text = raw.strip() if isinstance(raw, str) else raw
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
