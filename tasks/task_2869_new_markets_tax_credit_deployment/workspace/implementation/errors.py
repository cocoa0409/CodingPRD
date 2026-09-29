"""Error catalogue of PRD section 5."""

HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_CDE_NOT_FOUND": 404,
    "ERR_ALLOCATION_AWARD_NOT_FOUND": 404,
    "ERR_CENSUS_TRACT_NOT_FOUND": 404,
    "ERR_QALICB_NOT_FOUND": 404,
    "ERR_INVESTMENT_FUND_NOT_FOUND": 404,
    "ERR_QEI_NOT_FOUND": 404,
    "ERR_QLICI_NOT_FOUND": 404,
    "ERR_REINVESTMENT_OBLIGATION_NOT_FOUND": 404,
    "ERR_CBA_NOT_FOUND": 404,
    "ERR_UNWIND_NOT_FOUND": 404,
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_STALE_AWARD_VERSION": 412,
    "ERR_DUPLICATE_CERTIFICATION_NUMBER": 409,
    "ERR_DUPLICATE_TRACT_CODE": 409,
    "ERR_CDE_NOT_CERTIFIED": 409,
    "ERR_AWARD_NOT_ACTIVE": 409,
    "ERR_AWARD_POSTURE_RESTRICTED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_QEI_RECAPTURED": 409,
    "ERR_TEST_SEQUENCE_INVALID": 409,
    "ERR_TEST_WINDOW_OVERLAP": 409,
    "ERR_REPORT_PERIOD_OVERLAP": 409,
    "ERR_QALICB_COMPLIANCE_PERIOD_CONFLICT": 409,
    "ERR_UNWIND_ALREADY_OPEN": 409,
    "ERR_TRACT_NOT_LIC_ELIGIBLE": 422,
    "ERR_QALICB_NOT_CERTIFIED": 422,
    "ERR_QALICB_DISQUALIFIED": 422,
    "ERR_CBA_BREACHED": 422,
    "ERR_CBA_MISSING": 422,
    "ERR_FUND_NOT_FUNDED": 422,
    "ERR_DEPLOYMENT_WINDOW_CLOSED": 422,
    "ERR_OPTION_WINDOW_CLOSED": 422,
    "ERR_REINVESTMENT_DEADLINE_PASSED": 422,
    "ERR_OUTSIDE_SERVICE_AREA": 422,
    "ERR_COMPLIANCE_PERIOD_NOT_COMPLETE": 422,
    "ERR_CAPITAL_STACK_SHORTFALL": 422,
    "ERR_INSUFFICIENT_ALLOCATION_AUTHORITY": 422,
    "ERR_INSUFFICIENT_UNINVESTED_CASH": 422,
    "ERR_REPAYMENT_EXCEEDS_PRINCIPAL": 422,
    "ERR_REINVESTMENT_EXCEEDS_OBLIGATION": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "The X-User-ID or X-User-Role header is missing, empty or unrecognised.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The reviewer who performed the latest eligibility test may not run this annual compliance test.",
    "ERR_INVALID_REQUEST": "A required field is missing, mistyped, out of range or carries an undeclared enum value.",
    "ERR_INVALID_PAGINATION": "limit must be an integer from 1 through 100 and offset a non-negative integer.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."
        )
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
