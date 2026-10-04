"""Error types and the exact error-id -> HTTP status catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_MISSING_IDEMPOTENCY_KEY": 400,
    "ERR_IDEMPOTENCY_REPLAY_MISMATCH": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_COMMUNITY_NOT_OPEN": 409,
    "ERR_INVALID_PHASE_TRANSITION": 409,
    "ERR_HOME_NOT_COMPLETE": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_CONTRACT_EXHAUSTED": 409,
    "ERR_TAKEDOWN_WINDOW_NOT_OPEN": 409,
    "ERR_TAKEDOWN_WINDOW_EXPIRED": 409,
    "ERR_LOT_NOT_AVAILABLE": 409,
    "ERR_HOME_NOT_UNSOLD": 409,
    "ERR_STARTS_QUOTA_EXCEEDED": 409,
    "ERR_STARTS_BLOCKED_OVERHELD": 409,
    "ERR_NO_CAPACITY_REMAINING": 409,
    "ERR_NO_PUBLISHED_PACING_PLAN": 409,
    "ERR_CAPACITY_PERIOD_OVERLAP": 409,
    "ERR_CAPACITY_BELOW_ALLOCATED": 409,
    "ERR_INCENTIVE_WINDOW_CONFLICT": 409,
    "ERR_SERIES_BAND_OVERLAP": 422,
    "ERR_PRICE_OUT_OF_SERIES_BAND": 422,
    "ERR_PRICE_BELOW_NET_FLOOR": 422,
    "ERR_SALES_CONTRACT_NOT_TERMINABLE": 409,
}


def err(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
