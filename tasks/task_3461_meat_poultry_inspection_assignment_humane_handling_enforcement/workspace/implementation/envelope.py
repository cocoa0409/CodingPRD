"""Response envelope builders (PRD §2.2, §2.3).

Success: {"meta": {"api_request_id", "api_request_timestamp"[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import secrets
import string

from flask import jsonify, request

import store
from errors import ApiError


def _request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _meta(with_pagination=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": store.wallclock_iso3(),
    }
    if with_pagination is not None:
        meta["limit"] = with_pagination["limit"]
        meta["offset"] = with_pagination["offset"]
        meta["total_count"] = with_pagination["total_count"]
        meta["has_more"] = with_pagination["has_more"]
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": store.serialize(data)}
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {
        "meta": _meta(page),
        "response_type": "array",
        "data": [store.serialize(i) for i in items],
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Return the request JSON body as a dict; malformed JSON -> 400.

    Endpoints with no documented input tolerate an absent/empty body and
    receive an empty dict.
    """
    from errors import raise_err, ERR_INVALID_REQUEST

    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise_err(ERR_INVALID_REQUEST, "request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return parsed


def pagination_params():
    """Parse limit/offset per PRD §2.3 (default 10 / 0, limit clamped 1..100)."""
    def _parse(raw, default):
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = _parse(request.args.get("limit"), 10)
    offset = _parse(request.args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_and_page(rows, limit, offset):
    """Sort by created_at ascending (insertion order breaks ties) and page."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    total = len(ordered)
    return ordered[offset:offset + limit], total
