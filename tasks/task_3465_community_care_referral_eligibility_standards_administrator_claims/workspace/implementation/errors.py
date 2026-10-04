"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# error_id -> HTTP status, verbatim from PRD section 5
ERROR_CATALOG = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_STATE": 409,
    "ERR_REFERRAL_NOT_ACTIVE": 409,
    "ERR_TPA_SUSPENDED": 409,
    "ERR_ASSESSMENT_SUPERSEDED": 409,
    "ERR_EXTENSION_WINDOW_CLOSED": 409,
    "ERR_SERVICE_NOT_ELIGIBLE": 422,
    "ERR_PROVIDER_NOT_CREDENTIALED": 422,
    "ERR_CONTROLLED_RX_NOT_ALLOWED": 422,
    "ERR_DOCS_OUTSTANDING": 422,
    "ERR_DOCS_NOT_ACCEPTED": 422,
    "ERR_UNTIMELY_FILED": 422,
    "ERR_SERVICE_DATE_OUTSIDE_EPISODE": 422,
    "ERR_AUTH_WINDOW_VIOLATION": 422,
    "ERR_SAME_DAY_URGENT_VISIT": 422,
    "ERR_APPOINTMENT_SLOT_CONFLICT": 409,
    "ERR_EPISODE_OVERLAP": 409,
    "ERR_EXTENSION_CAP": 409,
    "ERR_NO_VISITS_REMAINING": 409,
    "ERR_DAYS_SUPPLY_EXCEEDED": 409,
    "ERR_RESUBMISSION_LIMIT": 409,
    "ERR_SERVICE_CODE_MISMATCH": 422,
    "ERR_PROVIDER_SERVICE_MISMATCH": 422,
    "ERR_NO_MATCHING_COMPLETED_APPOINTMENT": 422,
    "ERR_AMOUNT_INVALID": 422,
    "ERR_DOCUMENTATION_NOT_PENDING": 409,
    "ERR_DOC_NOT_REVIEWABLE": 409,
}


def fail(error_id, message):
    """Raise the catalogued error with a human-readable message."""
    raise ApiError(error_id, ERROR_CATALOG[error_id], message)
