"""Error classes and error ID constants (catalog from SCAFFOLD.yaml / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog: error_id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TERM_DATE_INVALID": 422,
    "ERR_TERM_NOT_OPEN": 422,
    "ERR_TERM_CLOCK_NOT_REACHED": 422,
    "ERR_STATE_NOT_AUTHORIZED": 422,
    "ERR_DISCLOSURE_REQUIRED": 422,
    "ERR_LICENSURE_DISCLOSURE_REQUIRED": 422,
    "ERR_INCENTIVE_COMP_VIOLATION": 422,
    "ERR_EVALUATION_INCOMPLETE": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_CASELOAD_CAP_EXCEEDED": 422,
    "ERR_SECTION_NOT_OPEN": 422,
    "ERR_SECTION_FULL": 422,
    "ERR_AUTHORIZATION_WINDOW_OVERLAP": 422,
    "ERR_CONTACT_CADENCE_EXCEEDED": 422,
    "ERR_OUTREACH_CADENCE": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_ALERT_THRESHOLD_NOT_MET": 422,
    "ERR_ADD_DROP_CLOSED": 422,
    "ERR_WITHDRAWAL_WINDOW_CLOSED": 422,
    "ERR_FINANCIAL_HOLD": 422,
    "ERR_PACKAGE_ALREADY_EXISTS": 409,
}


def raise_err(error_id, message):
    raise ApiError(error_id, ERRORS[error_id], message)
