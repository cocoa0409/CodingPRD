"""Error catalog: identifiers, HTTP statuses and the API exception type.

Every error_id and HTTP status here is copied verbatim from the scaffold's error
catalogue and PRD section 5.
"""


class ApiError(Exception):
    """Raised anywhere in the service layer; rendered by app.py's error handler."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# ---------------------------------------------------------------------------
# HTTP statuses per the error catalogue
# ---------------------------------------------------------------------------
STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SUBSCRIBER_LINE_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_PORT_REQUEST_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_PROTECTION_CASE_NOT_FOUND": 404,
    "ERR_MIGRATION_REQUEST_NOT_FOUND": 404,
    "ERR_LINE_ADDITION_REQUEST_NOT_FOUND": 404,
    "ERR_TRADE_IN_ASSESSMENT_NOT_FOUND": 404,
    "ERR_INSTALLMENT_PLAN_NOT_FOUND": 404,
    "ERR_REJECTION_CODE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DEVICE_PLAN_STATE": 409,
    "ERR_PLAN_NOT_ACTIVE": 409,
    "ERR_PORT_PROTECTION_ACTIVE": 403,
    "ERR_IDENTITY_NOT_VERIFIED": 403,
    "ERR_PROTECTION_ALREADY_ACTIVE": 409,
    "ERR_CREDIT_CLASS_BLOCKED": 403,
    "ERR_LINE_NOT_ACTIVE": 403,
    "ERR_DEPOSIT_REQUIRED": 402,
    "ERR_LINE_LIMIT_EXCEEDED": 409,
    "ERR_LINE_COUNT_OUT_OF_RANGE": 422,
    "ERR_TRANSFER_PIN_MISMATCH": 422,
    "ERR_RESUBMISSION_NOT_ALLOWED": 422,
    "ERR_RESUBMISSION_COOLDOWN": 409,
    "ERR_MDN_ALREADY_RESERVED": 409,
    "ERR_MDN_CONFLICT": 409,
    "ERR_RESERVATION_WINDOW_OVERLAP": 409,
    "ERR_RESERVATION_WINDOW_CLOSED": 409,
    "ERR_PROMO_WINDOW_OVERLAP": 409,
    "ERR_STALE_SUBSCRIBER_LINE_VERSION": 412,
}


def fail(error_id, message=None):
    """Raise the catalogued error with its declared HTTP status."""
    status = STATUS.get(error_id, 400)
    if message is None:
        message = error_id
    raise ApiError(error_id, status, message)