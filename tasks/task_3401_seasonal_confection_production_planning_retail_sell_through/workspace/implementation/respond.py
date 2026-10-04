"""Response envelope helpers — PRD 2.2 / SCAFFOLD 1.0 verbatim.

Success: { "meta": {api_request_id, api_request_timestamp[, limit, offset,
                    total_count, has_more]},
           "response_type": "object" | "array",
           "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error",
           "data": { "error_id": ..., "message": ... } }

Pagination: limit (default 10, min 1, max 100), offset (default 0).
"""

import uuid

from flask import jsonify, request

from db import now_ts3
from errors import ApiError, ERR_INVALID_REQUEST


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": now_ts3(),
    }


def ok(data, status=200):
    """Single-resource success envelope (response_type "object")."""
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    """Creation success envelope: HTTP 201."""
    return ok(data, status=201)


def ok_list(items, total_count, limit, offset):
    """List envelope (response_type "array") with pagination fields in meta."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Parse and validate limit/offset query parameters per PRD 2.3."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(400, ERR_INVALID_REQUEST, "limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not raw_limit.strip().lstrip("+").isdigit():
            raise ApiError(400, ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(400, ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(400, ERR_INVALID_REQUEST, "offset must be an integer")
        if str(raw_offset).strip() != str(offset) and not raw_offset.strip().lstrip("+").isdigit():
            raise ApiError(400, ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise ApiError(400, ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit=None, offset=None):
    """Sort by created_at ascending (insertion order breaks ties), then page.

    Callers should prefer calling parse_pagination() themselves BEFORE
    authorize() so that syntactic query validation precedes the numbered
    priorities (PRD 2.8), then pass the values here.
    """
    if limit is None:
        limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def _not_found(err):
        return error_body(ApiError(404, "ERR_NOT_FOUND", "route not found"))

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_body(ApiError(405, "ERR_METHOD_NOT_ALLOWED", "method not allowed"))

    @app.errorhandler(500)
    def _internal(err):
        return error_body(ApiError(500, "ERR_INTERNAL", "internal server error"))
