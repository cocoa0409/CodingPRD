"""Error catalog (scaffold 1.6 / PRD 5) and the ApiError exception.

ERROR_HTTP maps every error_id the API can emit to its HTTP status. The three
framework-level ids at the bottom are only used for unmatched routes / wrong
methods / unexpected exceptions — they are never produced by a declared
endpoint path.
"""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


ERROR_HTTP = {
    # auth / shape / existence
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TREND_SIGNAL_NOT_FOUND": 404,
    "ERR_CONCEPT_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_MANUFACTURER_NOT_FOUND": 404,
    "ERR_FORMULA_PROJECT_NOT_FOUND": 404,
    "ERR_COST_QUOTE_NOT_FOUND": 404,
    "ERR_DOSSIER_NOT_FOUND": 404,
    "ERR_RETAIL_PARTNER_NOT_FOUND": 404,
    "ERR_LINE_REVIEW_NOT_FOUND": 404,
    "ERR_PLANOGRAM_SLOT_NOT_FOUND": 404,
    "ERR_LAUNCH_PLAN_NOT_FOUND": 404,
    "ERR_DISCONTINUATION_REVIEW_NOT_FOUND": 404,
    # state / concurrency
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    # business rules
    "ERR_TREND_SCORE_BELOW_THRESHOLD": 422,
    "ERR_TREND_NOT_SELECTED": 422,
    "ERR_DUPLICATE_CONCEPT_NAME": 409,
    "ERR_INVALID_PRICE_POINT": 422,
    "ERR_CONCEPT_NOT_SELECTED": 422,
    "ERR_FORMULA_NOT_APPROVED": 422,
    "ERR_QUOTE_NOT_ACCEPTED": 422,
    "ERR_PRODUCT_NOT_SOURCING": 422,
    "ERR_PRODUCT_NOT_LAUNCH_READY": 422,
    "ERR_CM_SUSPENDED": 422,
    "ERR_QUOTE_EXPIRED": 422,
    "ERR_BELOW_MOQ": 422,
    "ERR_COST_TARGET_EXCEEDED": 422,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_DOSSIER_ALREADY_EXISTS": 409,
    "ERR_COMPLIANCE_GATE_FAILED": 422,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_SUBMISSION_WINDOW_CLOSED": 422,
    "ERR_OCCUPANCY_CONFLICT": 409,
    "ERR_UNRESOLVED_SLOTS": 422,
    "ERR_SLOT_NOT_COMMITTED": 422,
    "ERR_LAUNCH_WINDOW_NOT_OPEN": 422,
    "ERR_BUDGET_EXCEEDED": 422,
    "ERR_SAMPLE_OVERDRAW": 422,
    "ERR_SUCCESSOR_INVALID": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_DATE_RANGE": 422,
    # framework-level fallbacks (never emitted by declared endpoints)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


def err(error_id, message):
    """Build an ApiError using the catalogued HTTP status for error_id."""
    return ApiError(error_id, ERROR_HTTP[error_id], message)


def bad_request(message):
    return err("ERR_INVALID_REQUEST", message)


def not_found(error_id, message):
    return err(error_id, message)


def invalid_state(message):
    return err("ERR_INVALID_STATE", message)
