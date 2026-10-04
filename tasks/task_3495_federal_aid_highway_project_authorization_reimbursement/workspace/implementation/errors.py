"""Error catalog and the ApiError exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Complete error catalog: error_id -> HTTP status (PRD §5 / scaffold §1.6).
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_STIP_NOT_APPROVED": 409,
    "ERR_PROJECT_NOT_ELIGIBLE": 409,
    "ERR_ENVIRONMENTAL_NOT_CLEARED": 409,
    "ERR_ROW_NOT_CERTIFIED": 409,
    "ERR_AUTHORIZATION_NOT_OBLIGATED": 409,
    "ERR_OPEN_CHANGE_ORDERS": 409,
    "ERR_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_DBE_GOAL_NOT_MET": 422,
    "ERR_PUBLIC_INVOLVEMENT_INCOMPLETE": 422,
    "ERR_COMMENT_PERIOD_OPEN": 409,
    "ERR_ADVERTISEMENT_PERIOD_SHORT": 409,
    "ERR_BILLING_PERIOD_OVERLAP": 409,
    "ERR_STIP_PERIOD_OVERLAP": 409,
    "ERR_AUDIT_RESPONSE_WINDOW_OPEN": 409,
    "ERR_AWARD_NOT_LOWEST_RESPONSIVE": 422,
    "ERR_BID_NOT_RESPONSIVE": 422,
    "ERR_NO_RESPONSIVE_BIDS": 422,
    "ERR_CLEARANCE_KIND_EXISTS": 409,
    "ERR_FINAL_VOUCHER_EXISTS": 409,
    "ERR_DUPLICATE_APPORTIONMENT": 409,
    "ERR_APPORTIONMENT_EXCEEDED": 422,
    "ERR_FISCAL_CONSTRAINT_VIOLATED": 422,
    "ERR_NO_APPORTIONMENT_FOR_FFY": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_INELIGIBLE_ACTIVITY": 422,
    "ERR_REPAYMENT_EXCEEDS_DUE": 422,
}


def err(error_id, message):
    """Build an ApiError with the catalogued HTTP status for error_id."""
    return ApiError(error_id, ERRORS[error_id], message)
