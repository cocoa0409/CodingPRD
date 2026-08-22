"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""
import random
import string

from flask import jsonify, request

import clock
from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.iso(clock.real_now()),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_array(items, code=200):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), code


def ok_list(items, limit, offset, total, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + limit < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def pagination():
    """PRD 2.3: limit defaults to 10, range [1, 100]; offset defaults to 0, min 0."""
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        text = raw.strip()
        if text.startswith("+"):
            text = text[1:]
        neg = text.startswith("-")
        digits = text[1:] if neg else text
        if not digits.isdigit():
            raise ValueError(name)
        return -int(digits) if neg else int(digits)
    except (ValueError, AttributeError):
        raise ApiError("ERR_INVALID_PAGINATION")


def page(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
