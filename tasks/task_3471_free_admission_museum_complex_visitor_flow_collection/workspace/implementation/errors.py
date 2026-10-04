"""API error type and the complete error catalog (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error id -> HTTP status, transcribed verbatim from PRD section 5 (40 ids).
ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_TIMED_PASS_NOT_USED_HERE": 409,
    "ERR_DUPLICATE_PASS": 409,
    "ERR_SLOT_QUOTA_EXHAUSTED": 409,
    "ERR_DAILY_QUOTA_EXHAUSTED": 409,
    "ERR_MUSEUM_CLOSED_ON_DATE": 409,
    "ERR_PASS_EXPIRED": 409,
    "ERR_SCREENING_THROUGHPUT_FULL": 409,
    "ERR_SALE_NOT_OPEN": 409,
    "ERR_PRESALE_MEMBER_ONLY": 409,
    "ERR_MEMBER_LAPSED": 409,
    "ERR_TICKET_QUOTA_EXHAUSTED": 409,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_VISIT_DATE_MISMATCH": 409,
    "ERR_GROUP_TOO_LARGE": 422,
    "ERR_PROGRAM_DAY_MISMATCH": 422,
    "ERR_PROGRAM_NOT_SCHEDULED": 409,
    "ERR_DOCENT_NOT_CERTIFIED": 422,
    "ERR_OBJECT_NOT_IN_COLLECTION": 409,
    "ERR_LOAN_PERIOD_CONFLICT": 409,
    "ERR_COURIER_REQUIRED": 409,
    "ERR_INDEMNITY_MINIMUM_NOT_MET": 409,
    "ERR_INDEMNITY_REQUIRES_COURIER": 409,
    "ERR_STALE_LOAN_VERSION": 412,
    "ERR_CONDITION_REPORT_REQUIRED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CULTURAL_PROPERTY_REVIEW_PENDING": 422,
    "ERR_OBJECT_ON_ACTIVE_LOAN": 409,
    "ERR_FUND_FROZEN": 409,
    "ERR_FUND_ACTIVITY_NOT_PERMITTED": 422,
    "ERR_INSUFFICIENT_FUND_AVAILABLE": 409,
    "ERR_STALE_REVIEW_VERSION": 412,
    "ERR_GALLERY_SCHEDULE_CONFLICT": 409,
    "ERR_RESEARCH_VISIT_CONFLICT": 409,
    "ERR_OBJECT_RESERVED_FOR_LOAN": 409,
    "ERR_NOT_TRUST_FUND": 422,
}


def fail(error_id, message):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, message, ERROR_HTTP_STATUS[error_id])
