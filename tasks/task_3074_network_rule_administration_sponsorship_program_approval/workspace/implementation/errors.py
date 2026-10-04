"""Error classes and error ID constants for the Network API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog (id -> http status)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_WINDOW_EXPIRED": 422,
    "ERR_CERTIFICATION_STALE": 422,
    "ERR_PROGRAM_NOT_ENABLED": 422,
    "ERR_RATE_NOT_FOUND": 422,
    "ERR_SETTLEMENT_INVALID": 422,
    "ERR_RULE_NOT_EFFECTIVE": 422,
    "ERR_SPONSOR_INACTIVE": 422,
    "ERR_DRAFT_LINES_REMAIN": 422,
    "ERR_MERCHANT_NOT_ACTIVE": 422,
    "ERR_INVALID_REQUEST": 400,
}


def raise_err(error_id, message):
    raise ApiError(error_id, message, ERR[error_id])
