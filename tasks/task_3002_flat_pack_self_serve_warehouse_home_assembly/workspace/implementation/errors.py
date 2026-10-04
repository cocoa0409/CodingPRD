"""Error classes and the error catalog (§5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# HTTP status per error id (§5 catalogue).
ERR = {
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_ARTICLE_NOT_FOUND": 404,
    "ERR_CARTON_NOT_FOUND": 404,
    "ERR_BIN_STOCK_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_BOOKING_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_RETURN_LINE_NOT_FOUND": 404,
    "ERR_STANDARD_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_BIN_STOCK": 409,
    "ERR_DUPLICATE_BOOKING": 409,
    "ERR_UNGRADED_LINES": 409,
    "ERR_RESERVATION_EXPIRED": 409,
    "ERR_ORDER_NOT_RETURNABLE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INSUFFICIENT_STOCK": 422,
    "ERR_MULTI_CARTON_SHORTAGE": 422,
    "ERR_BOOKING_NEVER_FITS": 422,
    "ERR_ACCESS_INFEASIBLE": 422,
    "ERR_CREW_WINDOW_CONFLICT": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_SLOT_IN_PAST": 422,
    "ERR_STANDARD_MISSING": 422,
    "ERR_RECEIPT_REQUIRED": 422,
    "ERR_RETURN_QTY_EXCEEDED": 422,
    "ERR_INSUFFICIENT_POINTS": 422,
    "ERR_CLAIM_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_VALUE_EXCEEDED": 422,
}


def raise_err(error_id, message=""):
    raise ApiError(error_id, ERR[error_id], message or error_id)
