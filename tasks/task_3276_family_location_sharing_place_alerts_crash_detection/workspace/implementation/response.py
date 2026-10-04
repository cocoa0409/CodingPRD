"""Response envelope helpers."""
import random
import string
from flask import jsonify, request
from db import now, iso


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta(paginated=False, limit=None, offset=None, total=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }
    if paginated:
        meta["limit"] = limit
        meta["offset"] = offset
        meta["total_count"] = total
        meta["has_more"] = (offset + limit) < total
    return meta


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return success(data, status=201)


def list_response(items, limit, offset, total):
    body = {
        "meta": _meta(paginated=True, limit=limit, offset=offset, total=total),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    """Read limit/offset query params with defaults limit=10 offset=0, clamped."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
