"""Error catalog: every error_id pinned to its PRD HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


HTTP_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_CLINIC_OWNERSHIP_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PROGRAM_TERMS": 400,
    "ERR_UNKNOWN_SKU": 400,
    "ERR_WINDOW_INVALID": 400,
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_ANALYZER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_TEST_ORDER_NOT_FOUND": 404,
    "ERR_SERVICE_CASE_NOT_FOUND": 404,
    "ERR_CLINIC_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_ANALYZER_INVALID_STATE": 409,
    "ERR_CONNECTIVITY_NOT_ACTIVE": 409,
    "ERR_PROFICIENCY_LAPSED": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_PERIOD_INVALID_STATE": 409,
    "ERR_TEST_ORDER_INVALID_STATE": 409,
    "ERR_SERVICE_CASE_INVALID_STATE": 409,
    "ERR_PRICING_AGREEMENT_WINDOW_OVERLAP": 409,
    "ERR_PLACEMENT_TERM_OVERLAP": 409,
    "ERR_RENEGOTIATION_CASELOAD_DELTA_INSUFFICIENT": 422,
    "ERR_OUTSTANDING_SHORTFALL_UNPAID": 402,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 402,
    "ERR_STALE_AGREEMENT_VERSION": 412,
}


def err(error_id, message):
    """Build an ApiError with the catalog-pinned HTTP status."""
    return ApiError(error_id, HTTP_STATUS[error_id], message)
