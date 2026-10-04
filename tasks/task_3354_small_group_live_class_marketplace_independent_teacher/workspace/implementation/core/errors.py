"""Error catalogue for the Outschool Marketplace API (PRD section 5)."""


class ApiError(Exception):
    """Carries the catalogued error_id, its HTTP status and a human message."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


# error_id -> HTTP status (PRD section 5 catalogue)
HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_REFERENTIAL_INTEGRITY": 409,
    "ERR_MISSING_REQUIRED_FIELD": 400,
    "ERR_INVALID_ENUM_VALUE": 400,
    "ERR_INVALID_AGE_BAND": 400,
    "ERR_INVALID_TIME_WINDOW": 400,
    "ERR_CAPACITY_EXCEEDS_LISTING": 400,
    "ERR_SAMPLE_TOO_SHORT": 400,
    "ERR_LISTING_NOT_APPROVED": 409,
    "ERR_LISTING_NOT_PUBLISHED": 409,
    "ERR_TEACHER_NOT_ACTIVE": 409,
    "ERR_TEACHER_SUSPENDED": 409,
    "ERR_SECTION_FULL": 409,
    "ERR_SECTION_ALREADY_STARTED": 409,
    "ERR_SECTION_NOT_OPEN": 409,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_LEARNER_AGE_OUT_OF_RANGE": 409,
    "ERR_COUPON_NOT_FOUND": 404,
    "ERR_COUPON_ALREADY_REDEEMED": 409,
    "ERR_CREDIT_INSUFFICIENT": 409,
    "ERR_MIN_ENROLLMENT_NOT_MET": 409,
    "ERR_SCREENING_FAILED": 409,
    "ERR_SCREENING_STALE": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_APPLICATION_NOT_APPROVED": 409,
    "ERR_REVIEWER_CONFLICT": 409,
    "ERR_PAYOUT_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_PAYOUT_PERIOD": 409,
    "ERR_TAX_DOC_MISSING": 409,
    "ERR_PAYOUT_NOT_APPROVED": 409,
    "ERR_PAYOUT_ALREADY_PAID": 409,
    "ERR_PAYOUT_CAP_EXCEEDED": 409,
    "ERR_REPORT_WINDOW_CLOSED": 409,
    "ERR_REPORT_SLA_EXPIRED": 409,
}


def fail(error_id, message):
    raise ApiError(error_id, message)
