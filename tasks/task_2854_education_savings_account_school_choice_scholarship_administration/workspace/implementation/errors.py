"""Error catalogue (PRD section 5) and the API exception type."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- catalogue: error_id -> http status -------------------------------------
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PROGRAM_YEAR_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_EXPENSE_CATEGORY_NOT_FOUND": 404,
    "ERR_PURCHASE_REQUEST_NOT_FOUND": 404,
    "ERR_MISUSE_CASE_NOT_FOUND": 404,
    "ERR_RENEWAL_REVIEW_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_NOT_ACCOUNT_HOLDER": 403,
    "ERR_NOT_ASSIGNED_PROVIDER": 403,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_PROGRAM_YEAR_NOT_ACTIVE": 409,
    "ERR_APPLICATION_WINDOW_CLOSED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ACCOUNT_SUSPENDED": 409,
    "ERR_APPEAL_ROUNDS_EXHAUSTED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_FRAUD_RISK_TOO_HIGH": 422,
    "ERR_PROVIDER_NOT_ELIGIBLE": 422,
    "ERR_CATEGORY_NOT_AUTHORIZED": 422,
    "ERR_EXPENSE_NOT_ALLOWABLE": 422,
    "ERR_PREAPPROVAL_REQUIRED": 422,
    "ERR_OVERLAPPING_ENROLLMENT_PERIOD": 409,
    "ERR_DUPLICATE_SERVICE_PERIOD": 409,
    "ERR_SERVICE_PERIOD_OUTSIDE_TERM": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_RESIDENCY_NOT_ELIGIBLE": 422,
    "ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT": 422,
    "ERR_CATEGORY_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_BALANCE": 402,
    "ERR_NO_SEATS_AVAILABLE": 409,
    "ERR_CLAIM_AMOUNT_MISMATCH": 422,
}


def fail(error_id, message=None):
    """Raise the catalogued error with its declared HTTP status."""
    raise ApiError(error_id, CATALOG[error_id], message)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)
