"""Error catalog for the Wetland Permit Review API.

Every error_id and HTTP status below is taken verbatim from SCAFFOLD.yaml
§1.6 / PRD.md §5 (56 codes).
"""


class ApiError(Exception):
    """Exception carrying the scaffold-declared error_id and HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERROR_CATALOG = {
    # auth / ownership
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # shape
    "ERR_INVALID_REQUEST": 400,
    # existence (404)
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_JD_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_AA_NOT_FOUND": 404,
    "ERR_COMMENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_BANK_NOT_FOUND": 404,
    "ERR_CREDIT_TXN_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    # state (409)
    "ERR_JD_INVALID_STATE": 409,
    "ERR_APPEAL_INVALID_STATE": 409,
    "ERR_APPLICATION_INVALID_STATE": 409,
    "ERR_AA_INVALID_STATE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_CREDIT_TXN_INVALID_STATE": 409,
    "ERR_PERMIT_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_BANK_NOT_OPERATIONAL": 409,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # domain rules (422 unless noted)
    "ERR_CLOCK_REGRESSION": 422,
    "ERR_JD_NOT_APPEALABLE": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_JD_EXPIRED": 409,
    "ERR_COMMENT_PERIOD_CLOSED": 422,
    "ERR_NOTICE_PERIOD_STILL_OPEN": 422,
    "ERR_GENERAL_PERMIT_INELIGIBLE": 422,
    "ERR_LEDPA_NOT_DEMONSTRATED": 422,
    "ERR_PUBLIC_INTEREST_UNFAVORABLE": 422,
    "ERR_JD_NOT_JURISDICTIONAL": 422,
    "ERR_AA_NOT_ACCEPTED": 422,
    "ERR_UNRESOLVED_AGENCY_OBJECTIONS": 422,
    "ERR_ACTIVE_JD_EXISTS": 409,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_AA_ALREADY_EXISTS": 409,
    "ERR_NOTICE_ALREADY_PUBLISHED": 409,
    "ERR_ACTIVE_PLAN_EXISTS": 409,
    "ERR_OUT_OF_SERVICE_AREA": 422,
    "ERR_COVERAGE_INTERVAL_CONFLICT": 409,
    "ERR_EXTENSION_ALREADY_USED": 409,
    "ERR_INSUFFICIENT_CREDIT_INVENTORY": 422,
    "ERR_CREDITS_NOT_SECURED": 422,
    "ERR_INSUFFICIENT_FINANCIAL_ASSURANCE": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_MITIGATION_NOT_SECURED": 422,
    "ERR_REPORTS_OVERDUE_EXIST": 422,
    "ERR_MONITORING_INCOMPLETE": 422,
}


def api_err(error_id, message=None):
    """Build an ApiError with the catalogued HTTP status for error_id."""
    return ApiError(error_id, ERROR_CATALOG[error_id], message or error_id)
