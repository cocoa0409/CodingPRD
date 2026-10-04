"""Error catalog: every error id and its HTTP status (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ANNOUNCEMENT_NOT_OPEN": 409,
    "ERR_ANNOUNCEMENT_NOT_CLOSED": 409,
    "ERR_CERTIFICATE_NOT_ACTIVE": 409,
    "ERR_OFFER_NOT_ACTIONABLE": 409,
    "ERR_ASSESSMENT_NOT_SUBMITTED": 409,
    "ERR_PASS_OVER_NOT_PENDING": 409,
    "ERR_APPEAL_NOT_ALLOWED_STATE": 409,
    "ERR_APPLICATION_WRONG_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_SUITABILITY_NOT_FAVORABLE": 422,
    "ERR_CLEARANCE_INSUFFICIENT": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_ACTIVE_ASSESSMENT_EXISTS": 409,
    "ERR_ANNOUNCEMENT_PERIOD_OVERLAP": 409,
    "ERR_CERTIFICATE_WINDOW_OVERLAP": 409,
    "ERR_ACTIVE_CERTIFICATE_EXISTS": 409,
    "ERR_INSUFFICIENT_ELIGIBLES": 422,
    "ERR_CATEGORY_BYPASS": 422,
    "ERR_PASS_OVER_REQUIRED": 422,
    "ERR_NOT_PREFERENCE_ELIGIBLE": 422,
    "ERR_EXTENSION_LIMIT": 422,
    "ERR_NO_REMAINING_VACANCIES": 409,
    "ERR_DUPLICATE_KEY": 409,
    "ERR_APPEAL_GROUND_MISMATCH": 422,
    "ERR_SERIES_GRADE_RANGE": 422,
    "ERR_AUTHORITY_METHOD_MISMATCH": 422,
    "ERR_OUTSIDE_OPEN_PERIOD": 422,
    "ERR_APPEAL_WINDOW_EXPIRED": 422,
    "ERR_OFFER_RESPONSE_EXPIRED": 409,
    "ERR_EOD_DATE_INVALID": 422,
    "ERR_POSITION_NOT_CLASSIFIED": 422,
    "ERR_OUTSIDE_AREA_OF_CONSIDERATION": 422,
    "ERR_ELIGIBILITY_DOC_REQUIRED": 422,
    "ERR_PASS_OVER_PENDING": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_REVIEW_ALREADY_RECORDED": 409,
    "ERR_ASSESSMENT_NOT_APPLICABLE": 422,
}


def fail(error_id, message):
    raise ApiError(error_id, message, ERROR_STATUS[error_id])


def not_found(what="resource"):
    fail("ERR_NOT_FOUND", "%s not found" % what)


def invalid_request(message):
    fail("ERR_INVALID_REQUEST", message)


def forbidden(message="forbidden"):
    fail("ERR_FORBIDDEN", message)


def invalid_state(message="invalid state for requested transition"):
    fail("ERR_INVALID_STATE", message)
