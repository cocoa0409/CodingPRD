"""The response envelope (PRD 2.2) and offset pagination (PRD 2.3)."""

import random
import string

from flask import jsonify, request

import config
from errors import ApiError
from store import store

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.now_iso(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = offset + len(rows) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _page_param(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if text == "" or not _is_integer_text(text):
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    value = int(text)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_INVALID_PAGINATION", "%s is out of range" % name)
    return value


def _is_integer_text(text):
    body = text[1:] if text[:1] in "+-" else text
    return body.isdigit() and body != ""


def pagination():
    """Effective (limit, offset) for this request, refusing bad input."""
    limit = _page_param("limit", config.PAGE_LIMIT_DEFAULT, config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX)
    offset = _page_param("offset", config.PAGE_OFFSET_DEFAULT, config.PAGE_OFFSET_MIN)
    return limit, offset


def paginate(records, serializer):
    """Apply the page window to an already-ordered, already-filtered list."""
    limit, offset = pagination()
    total = len(records)
    window = records[offset : offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
