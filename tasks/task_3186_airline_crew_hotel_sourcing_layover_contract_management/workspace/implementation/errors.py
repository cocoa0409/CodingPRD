"""Error types and the scaffold error catalog (HTTP statuses per PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_DEADLINE_PASSED": 422,
    "ERR_NOT_NEGOTIABLE": 409,
    "ERR_REST_VIOLATION": 422,
    "ERR_BLACKOUT_DATE": 422,
    "ERR_ROOM_BLOCK_EXHAUSTED": 422,
    "ERR_LAYOVER_ALREADY_BOOKED": 409,
    "ERR_PICKUP_CONFLICT": 409,
    "ERR_VENDOR_INACTIVE": 422,
    "ERR_UNION_STANDARD_VIOLATION": 422,
    "ERR_TERMINATION_THRESHOLD": 422,
    "ERR_BUDGET_EXCEEDED": 422,
    "ERR_INVOICE_VARIANCE_EXCEEDED": 422,
}


def err(error_id, message):
    return ApiError(error_id, message, ERROR_HTTP[error_id])
