"""Error classes and the error catalog (PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_RATE_STALE": 409,
    "ERR_PRODUCT_NOT_ACTIVE": 409,
    "ERR_FEED_NOT_PUBLISHED": 409,
    "ERR_POLICY_NOT_IN_FORCE": 409,
    "ERR_AGENT_NOT_APPOINTED_IN_STATE": 409,
    "ERR_AGENT_TERMINATED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_APPOINTMENT_WINDOW_OVERLAP": 409,
    "ERR_FEED_WINDOW_OVERLAP": 409,
    "ERR_FEED_WINDOW_GAP_VIOLATION": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_CHANNEL_NOT_AVAILABLE": 409,
    "ERR_PRODUCT_NOT_PUBLISHABLE": 409,
    "ERR_AGENT_MISMATCH": 409,
    "ERR_BUNDLE_NOT_ELIGIBLE": 409,
    "ERR_AGENT_HAS_ACTIVE_PLACEMENTS": 409,
    "ERR_AOR_NOT_ALLOWED": 409,
    "ERR_TELEMATICS_ALREADY_ENROLLED": 409,
    "ERR_PREMIUM_CAP_EXCEEDED": 409,
    "ERR_NOTHING_TO_PAY": 409,
    "ERR_NEGATIVE_COMMISSION": 409,
    "ERR_DUPLICATE_RATER_CODE": 409,
    "ERR_DUPLICATE_CONSUMER_EMAIL": 409,
    "ERR_STALE_VERSION": 412,
}


def raise_err(error_id, message=""):
    raise ApiError(error_id, ERR[error_id], message or error_id)
