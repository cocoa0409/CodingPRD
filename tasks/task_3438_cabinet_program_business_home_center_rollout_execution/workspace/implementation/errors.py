"""API error type and the PRD section 5 error catalogue."""


class ApiError(Exception):
    """Carries error_id, HTTP status and a human-readable message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# PRD section 5 catalogue: error_id -> HTTP status
ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_HAS_OPEN_ORDERS": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_PROGRAM_TRANSITIONING": 409,
    "ERR_NO_ACTIVE_LINE": 409,
    "ERR_QUOTE_STALE": 409,
    "ERR_ORDER_NOT_CANCELLABLE": 409,
    "ERR_SHIPMENT_NOT_DELIVERED": 409,
    "ERR_LINE_NOT_COVERED": 422,
    "ERR_STORE_NOT_SERVICED": 422,
    "ERR_NO_CURRENT_BATCH": 422,
    "ERR_DESIGNER_WINDOW_OVERLAP": 409,
    "ERR_MEASURE_WINDOW_INVALID": 422,
    "ERR_DELIVERY_WEEK_INVALID": 422,
    "ERR_CLAIM_WINDOW_EXPIRED": 422,
    "ERR_SLOT_WEEK_PAST": 422,
    "ERR_DISPOSITION_WINDOW_EXPIRED": 422,
    "ERR_SLOT_EXISTS": 409,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_QUANTITY_EXCEEDED": 422,
    "ERR_COLOR_MISMATCH": 422,
    "ERR_NO_CAPACITY": 422,
    "ERR_CHANNEL_REQUIRES_DESIGN_JOB": 422,
    "ERR_DISPOSITION_OVERAGE": 422,
    "ERR_CREDIT_HOLD": 409,
}


def api_error(error_id, message):
    """Build an ApiError with the catalogue-pinned HTTP status."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message)
