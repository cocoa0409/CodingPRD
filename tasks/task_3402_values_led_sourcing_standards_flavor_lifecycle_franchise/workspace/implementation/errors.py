"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    """Carries an error_id, its catalogued HTTP status, and a message."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_SOD_AUDITOR_VERIFY": 403,
    "ERR_SOD_CAMPAIGN_PROPOSER": 403,
    "ERR_SUPPLIER_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_FLAVOR_NOT_FOUND": 404,
    "ERR_REVIVAL_REQUEST_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    "ERR_SHOP_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SUPPLIER_NOT_APPROVED": 409,
    "ERR_CERT_WINDOW_OVERLAP": 409,
    "ERR_CERT_WINDOW_INVALID": 422,
    "ERR_COMMITMENT_WINDOW_INVALID": 422,
    "ERR_PLANT_CAPACITY_EXCEEDED": 422,
    "ERR_ORDER_CAPACITY_EXCEEDED": 422,
    "ERR_SLOT_DATE_PAST": 422,
    "ERR_DUPLICATE_SIGNATURE": 409,
    "ERR_REVIVAL_WINDOW_EXPIRED": 422,
    "ERR_FLAVOR_NOT_RETIRED": 409,
    "ERR_FLAVOR_NOT_SCHEDULABLE": 409,
    "ERR_FLAVOR_NOT_PUBLISHABLE": 409,
    "ERR_PAYMENT_NOT_FINAL": 409,
    "ERR_CLAIM_COVERAGE_INSUFFICIENT": 422,
    "ERR_CERT_NOT_VERIFIED": 422,
    "ERR_CERT_SCOPE_MISMATCH": 422,
    "ERR_ORDER_FLAVOR_UNAVAILABLE": 422,
    "ERR_SHOP_NOT_OPERATING": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_RETAIL_NOTICES_PENDING": 409,
    "ERR_NONPROFIT_VERIFICATION_REQUIRED": 422,
    "ERR_CLOCK_REGRESSION": 422,
}


def fail(error_id, message):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, ERROR_HTTP[error_id], message)
