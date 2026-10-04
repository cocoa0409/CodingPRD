"""Error types and the error catalog (PRD section 5)."""


class ApiError(Exception):
    """Carries an error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# Error catalog identifiers -> HTTP status (PRD section 5).
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_ACCOUNT_MISMATCH": 403,
    "ERR_NOT_HEADNOTE_AUTHOR": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_HEADNOTE_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_USER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_USAGE_EVENT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_DOCUMENT_REMOVED": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DOCUMENT_NOT_PUBLISHED": 409,
    "ERR_DOCUMENT_SEALED": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_INVOICE_PERIOD_CLOSED": 409,
    "ERR_SEAT_ALREADY_HELD": 409,
    "ERR_NO_SEAT_HELD": 409,
    "ERR_NO_SEATS_AVAILABLE": 409,
    "ERR_REVIEWER_IS_AUTHOR": 422,
    "ERR_BULK_RATE_EXCEEDED": 422,
    "ERR_USAGE_OUT_OF_SCOPE": 422,
    "ERR_MATTER_CODE_REQUIRED": 422,
    "ERR_PLAN_ACCOUNT_INCOMPATIBLE": 422,
    "ERR_DUPLICATE_CITATION": 409,
    "ERR_SELF_CITATION": 422,
    "ERR_CITATION_TARGET_NOT_PUBLISHED": 409,
    "ERR_LICENSE_WINDOW_OVERLAP": 409,
    "ERR_REMOVAL_WINDOW_OVERLAP": 409,
    "ERR_SUBSCRIPTION_OVERLAP": 409,
    "ERR_STALE_VERSION": 412,
}


def raise_err(error_id, message):
    """Raise an ApiError with the catalog-pinned HTTP status."""
    raise ApiError(error_id, ERR[error_id], message)
