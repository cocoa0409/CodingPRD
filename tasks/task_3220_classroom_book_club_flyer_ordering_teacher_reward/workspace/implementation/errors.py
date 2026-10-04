"""Error catalog: exception class and helpers producing the standard error envelope."""

import uuid
import db


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_SCHOOL_RESTRICTED": 409,
    "ERR_LICENSE_SUSPENDED": 409,
    "ERR_ROYALTY_CAP_INVALID": 422,
    "ERR_GRADE_BAND_MISMATCH": 422,
    "ERR_FORMAT_NOT_ALLOWED": 422,
    "ERR_CYCLE_ALREADY_PUBLISHED": 409,
    "ERR_EMPTY_CYCLE": 422,
    "ERR_FAIR_OVERLAP": 409,
    "ERR_TITLE_OVERLAP_CAP": 409,
    "ERR_PROMO_WINDOW_INVALID": 422,
    "ERR_PROMO_SHAPE_INVALID": 422,
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_POINTS_BALANCE_NEGATIVE": 422,
    "ERR_NOT_LOW_INCOME": 422,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_ORDER_NOT_OPEN": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ORDER_HAS_SHIPPED": 409,
    "ERR_ORDER_EMPTY": 422,
    "ERR_CYCLE_NOT_PUBLISHED": 409,
    "ERR_DONATION_NOT_MATCHED": 409,
    "ERR_FAIR_NOT_CANCELLABLE": 409,
    "ERR_REDEMPTION_SHAPE_INVALID": 422,
    "ERR_ENROLLMENT_EXISTS": 409,
}


def raise_err(error_id, message):
    raise ApiError(error_id, ERROR_STATUS[error_id], message)


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": db.now_iso_ms(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
