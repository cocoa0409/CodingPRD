"""Response envelope helpers — SCAFFOLD §1.0 / PRD §2.2.

Success: {"meta": {api_request_id, api_request_timestamp, [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
from flask import jsonify

from errors import ApiError
from store import now
from util import fmt_ts, new_request_id


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def success(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def success_list(items, limit, offset, total_count, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _unmatched(err):
        return error_response(
            ApiError("ERR_NOT_FOUND", "route not found", 404)
        )

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "method not allowed", 405)
        )

    @app.errorhandler(Exception)
    def _internal(err):
        return error_response(
            ApiError("ERR_INTERNAL", f"internal error: {err}", 500)
        )
