"""The success and error envelopes of PRD §2.2 and the pagination of §2.3."""

import random
import string

from flask import jsonify, request

from clockcal import host_now_iso
from errors import fail

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": host_now_iso(),
    }


def ok(data, status=200):
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


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(raw):
    text = raw.strip()
    if text == "":
        return None
    if text.startswith("+"):
        return None
    neg = text.startswith("-")
    digits = text[1:] if neg else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if neg else value


def pagination():
    """Read and validate limit/offset (PRD §2.3, ladder band 9)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        parsed = _int_param(raw_limit)
        if parsed is None or parsed < PAGINATION_MIN_LIMIT or parsed > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_PAGINATION")
        limit = parsed
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        parsed = _int_param(raw_offset)
        if parsed is None or parsed < 0:
            fail("ERR_INVALID_PAGINATION")
        offset = parsed
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def listing(rows, serializer):
    """Apply §2.3 pagination to an already-ordered, already-filtered set."""
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset)
    return ok_list([serializer(r) for r in page], limit, offset, total)
