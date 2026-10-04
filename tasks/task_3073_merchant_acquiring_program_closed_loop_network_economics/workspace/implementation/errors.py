"""Error identifiers and the API exception type.

The identifier strings are exactly those of the PRD's §5 catalogue.
"""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_RESPOND_AMOUNT_TOO_LOW = "ERR_RESPOND_AMOUNT_TOO_LOW"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_MERCHANT_NOT_FOUND = "ERR_MERCHANT_NOT_FOUND"
ERR_NO_RISK_STATE = "ERR_NO_RISK_STATE"
ERR_POOL_INSUFFICIENT_RESERVE = "ERR_POOL_INSUFFICIENT_RESERVE"
ERR_PRIVACY_VIOLATION = "ERR_PRIVACY_VIOLATION"
ERR_MERCHANT_RISK_SUPPRESSED = "ERR_MERCHANT_RISK_SUPPRESSED"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SUPPRESS_ALREADY_TERMINAL = "ERR_SUPPRESS_ALREADY_TERMINAL"
ERR_BATCH_SEQ_NOT_MONOTONE = "ERR_BATCH_SEQ_NOT_MONOTONE"
ERR_COMPLAINT_ALREADY_ENROLLED = "ERR_COMPLAINT_ALREADY_ENROLLED"
ERR_TEMPORAL_OVERLAP = "ERR_TEMPORAL_OVERLAP"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# HTTP statuses, from the PRD §5 catalogue.
ERROR_HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN: 403,
    ERR_RESPOND_AMOUNT_TOO_LOW: 403,
    ERR_NOT_FOUND: 404,
    ERR_MERCHANT_NOT_FOUND: 404,
    ERR_NO_RISK_STATE: 409,
    ERR_POOL_INSUFFICIENT_RESERVE: 402,
    ERR_PRIVACY_VIOLATION: 403,
    ERR_MERCHANT_RISK_SUPPRESSED: 409,
    ERR_INVALID_STATE: 409,
    ERR_SUPPRESS_ALREADY_TERMINAL: 409,
    ERR_BATCH_SEQ_NOT_MONOTONE: 409,
    ERR_COMPLAINT_ALREADY_ENROLLED: 409,
    ERR_TEMPORAL_OVERLAP: 409,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_REQUEST: 400,
}

# Human-readable defaults; call sites may pass a more specific message.
ERROR_MESSAGES = {
    ERR_UNAUTHENTICATED: "Authentication headers are missing or invalid.",
    ERR_FORBIDDEN: "The acting role is not permitted for this operation.",
    ERR_RESPOND_AMOUNT_TOO_LOW: "The dispute amount is below the response minimum.",
    ERR_NOT_FOUND: "The referenced resource does not exist.",
    ERR_MERCHANT_NOT_FOUND: "The referenced merchant does not exist.",
    ERR_NO_RISK_STATE: "The merchant has no risk-state row.",
    ERR_POOL_INSUFFICIENT_RESERVE: "The funded redemption pool cannot cover the redemption.",
    ERR_PRIVACY_VIOLATION: "Member spend data may not be shared at this privacy state.",
    ERR_MERCHANT_RISK_SUPPRESSED: "The merchant has crossed a risk ceiling.",
    ERR_INVALID_STATE: "The resource is not in the state required for this transition.",
    ERR_SUPPRESS_ALREADY_TERMINAL: "The merchant is already in the terminal suppressed state.",
    ERR_BATCH_SEQ_NOT_MONOTONE: "The funding batch sequence is not strictly ascending.",
    ERR_COMPLAINT_ALREADY_ENROLLED: "The merchant is already enrolled as a prospect.",
    ERR_TEMPORAL_OVERLAP: "The requested live window violates the one-day clearance buffer.",
    ERR_STALE_VERSION: "The supplied version is stale.",
    ERR_INVALID_REQUEST: "The request body is malformed.",
}


class ApiError(Exception):
    """An error that maps directly onto the PRD error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or ERROR_MESSAGES.get(error_id, "Request failed.")
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)


def invalid_request(message=None):
    return ApiError(ERR_INVALID_REQUEST, message)