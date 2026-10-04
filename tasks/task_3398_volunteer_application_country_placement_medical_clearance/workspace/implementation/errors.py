"""ApiError type, response envelope builders, pagination, and error handlers.

Envelope (SCAFFOLD response_envelope / PRD 2.2):
  success: {"meta": {api_request_id, api_request_timestamp, [pagination]},
            "response_type": "object" | "array", "data": ...}
  error:   {"meta": {api_request_id, api_request_timestamp},
            "response_type": "error", "data": {"error_id", "message"}}
Pagination fields: limit (default 10, min 1, max 100), offset (default 0),
total_count, has_more — carried in meta on list responses only.
"""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


def _meta():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)
    return {"api_request_id": "req_" + uuid.uuid4().hex,
            "api_request_timestamp": stamp}


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def pagination_params():
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err("ERR_VALIDATION", 400, "limit and offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        err("ERR_VALIDATION", 400,
            "limit must be within 1..100 and offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: full sorted list; returns a paginated envelope response."""
    limit, offset = pagination_params()
    total = len(records)
    return ok_list(records[offset:offset + limit], limit, offset, total)


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(e):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": e.error_id, "message": e.message}}), e.http_status

    @app.errorhandler(404)
    def _not_found(e):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_NOT_FOUND",
                                 "message": "Resource not found"}}), 404

    @app.errorhandler(405)
    def _method_not_allowed(e):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED",
                                 "message": "Method not allowed"}}), 405

    @app.errorhandler(Exception)
    def _internal(e):
        return jsonify({"meta": _meta(), "response_type": "error",
                        "data": {"error_id": "ERR_INTERNAL",
                                 "message": str(e)}}), 500
