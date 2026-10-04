"""Error catalog and ApiError exception. Error ids and HTTP statuses are read
verbatim from SCAFFOLD.yaml §1.6 / PRD §5."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_CONTEST_NOT_FOUND": 404,
    "ERR_COUNTY_NOT_FOUND": 404,
    "ERR_STRINGER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CALL_NOT_FOUND": 404,
    "ERR_RECOUNT_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_POSTURE_FORBIDS": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_CALL_ALREADY_PUBLISHED": 409,
    "ERR_RECOUNT_ACTIVE_BLOCKS_CALL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CERTAINTY_NOT_MET": 422,
    "ERR_CROSS_EVENT_REFERENCE": 422,
    "ERR_CANDIDATE_NOT_IN_CONTEST": 422,
    "ERR_COUNTY_NOT_IN_CONTEST": 422,
    "ERR_STRINGER_NOT_DEPLOYED": 422,
    "ERR_FEED_COVERAGE_MISSING": 422,
    "ERR_NO_ELIGIBLE_STRINGER": 422,
    "ERR_ASSIGNMENT_WINDOW_OVERLAP": 409,
    "ERR_OUTSIDE_ASSIGNMENT_WINDOW": 409,
    "ERR_PRECINCTS_EXCEED_EXPECTED": 422,
    "ERR_RECOUNT_MARGIN_EXCEEDED": 422,
    "ERR_COVERAGE_BUDGET_EXCEEDED": 422,
    "ERR_DUPLICATE_COUNTY": 409,
    "ERR_DUPLICATE_FEED": 409,
    "ERR_DUPLICATE_CANDIDATE": 409,
    "ERR_DUPLICATE_COUNTY_LINK": 409,
    "ERR_DUPLICATE_INVOICE": 409,
    "ERR_LICENSE_TIER_FORBIDS": 403,
}


def raise_err(error_id, message=None):
    """Raise an ApiError with the catalogued HTTP status for error_id."""
    raise ApiError(error_id, ERROR_CATALOG[error_id], message or error_id)
