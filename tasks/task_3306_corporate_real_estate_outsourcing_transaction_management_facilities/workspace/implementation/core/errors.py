"""Error catalogue and exception type."""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_ASSIGNED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ACCOUNT_CLOSED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_OFFBOARDING_PENDING": 409,
    "ERR_NOT_TRANSITIONING": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_BROKER_NOT_LICENSED": 422,
    "ERR_CONSENT_REQUIRED": 422,
    "ERR_LEASE_EXPIRED": 422,
    "ERR_MARKET_MISMATCH": 422,
    "ERR_LEASE_OVERLAP": 422,
    "ERR_SITE_OVERLAP": 422,
    "ERR_COMMISSION_EXCEEDS_FEE": 422,
    "ERR_SITE_EXCEEDS_PORTFOLIO": 422,
    "ERR_SQFT_MISMATCH": 422,
    "ERR_APPROVAL_LEVEL_INSUFFICIENT": 422,
    "ERR_FEE_ACCRUAL_LOCKED": 409,
    "ERR_CLOCK_ALREADY_ADVANCED": 409,
    "ERR_TRANSITION_INCOMPLETE": 422,
    "ERR_BLOCKING_TASK_OPEN": 422,
    "ERR_COOLING_OFF_ACTIVE": 422,
    "ERR_LEASE_OVERDUE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message="", http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def not_found(message="No resource matches the supplied identifier."):
    return ApiError("ERR_RESOURCE_NOT_FOUND", message)