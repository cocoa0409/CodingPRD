"""Error types and catalog."""
from flask import jsonify
import uuid
from db import ts_now


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_MILL_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_HEAT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_GRADE_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_SCORECARD_NOT_FOUND": 404,
    "ERR_SHEET_NOT_FOUND": 404,
    "ERR_INDEX_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_MILL_INTERRUPTED": 409,
    "ERR_BLEND_INFEASIBLE": 422,
    "ERR_CHEMISTRY_OUT_OF_SPEC": 422,
    "ERR_MTR_NOT_ISSUABLE": 409,
    "ERR_CONTRACT_PRICE_FORBIDDEN": 422,
    "ERR_CONTRACT_NOT_OPEN": 409,
    "ERR_LOT_DEPLETED": 409,
    "ERR_HEAT_SEQUENCE_CONFLICT": 409,
    "ERR_CAMPAIGN_OVERLAP": 409,
    "ERR_CAMPAIGN_WINDOW_VIOLATION": 409,
    "ERR_CAMPAIGN_EMPTY": 409,
    "ERR_HEAT_NOT_CAST": 409,
    "ERR_ROLL_CHANGE_BUDGET_EXCEEDED": 422,
    "ERR_EVENT_OVERLAP": 409,
    "ERR_UNRESOLVED_ORDERS": 409,
    "ERR_ACCOUNT_BLOCKED": 402,
    "ERR_INDEX_MISSING": 422,
    "ERR_UNDER_DELIVERED": 422,
    "ERR_WAIVER_DUPLICATE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, HTTP_STATUS[error_id], message)


def error_response(error_id, message, status):
    body = {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts_now(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_INVALID_REQUEST", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_INVALID_REQUEST", "method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_generic(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.status)
        return error_response("ERR_INVALID_REQUEST", str(e), 500)
