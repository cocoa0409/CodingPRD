"""Response envelope (PRD section 2.2) and pagination (PRD section 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _wall_clock_iso():
    now = datetime.now(timezone.utc)
    return "%s.%03dZ" % (now.strftime("%Y-%m-%dT%H:%M:%S"), now.microsecond // 1000)


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_clock_iso(),
    }


def single(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return single(data, 201)


def collection(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def failure(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _positive_int(raw):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_PAGINATION")
    if text.startswith("+"):
        text = text[1:]
    if not text.lstrip("-").isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    try:
        return int(text)
    except ValueError:
        raise ApiError("ERR_INVALID_PAGINATION")


def pagination():
    limit = _positive_int(request.args.get("limit"))
    offset = _positive_int(request.args.get("offset"))
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(records, serializer):
    from store import ordered

    limit, offset = pagination()
    items = ordered(records)
    total = len(items)
    window = items[offset:offset + limit]
    return collection([serializer(r) for r in window], limit, offset, total)
