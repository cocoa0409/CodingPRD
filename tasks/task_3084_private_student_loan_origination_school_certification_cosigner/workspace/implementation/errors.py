"""Error catalogue for the Private Student Loan Origination API.

Every error_id / http_status pair below is taken verbatim from SCAFFOLD.yaml
section 1.6 and PRD.md section 5.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_BORROWER_NOT_FOUND": 404,
    "ERR_COSIGNER_NOT_FOUND": 404,
    "ERR_SCHOOL_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_LOAN_CHILD_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_CLOCK": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SCHOOL_CAPACITY_EXCEEDED": 409,
    "ERR_CERTIFICATION_PERIOD_CONFLICT": 409,
    "ERR_DISBURSEMENT_BLOCKED": 409,
    "ERR_DISBURSEMENT_WINDOW_OVERLAP": 409,
    "ERR_FORBEARANCE_OVERLAP": 409,
    "ERR_PLAN_REQUIRED": 409,
    "ERR_NOTICE_OBLIGATION_PENDING": 409,
    "ERR_COSIGNER_REQUIRED": 422,
    "ERR_CREDIT_DECLINED": 422,
    "ERR_AMOUNT_OUT_OF_RANGE": 422,
    "ERR_CERTIFICATION_LIMIT_EXCEEDED": 422,
    "ERR_DISBURSEMENT_OVER_CERTIFIED": 422,
    "ERR_DEFERMENT_CAP_EXCEEDED": 422,
    "ERR_PRODUCT_RULE_UNSUPPORTED": 422,
    "ERR_RELEASE_RUN_INSUFFICIENT": 422,
    "ERR_RELEASE_UNDERWRITING_FAILED": 422,
    "ERR_COSIGNER_NOT_ELIGIBLE": 422,
    "ERR_LOAN_DELINQUENT": 422,
    "ERR_DEFAULT_THRESHOLD_NOT_MET": 422,
}


class ApiError(Exception):
    """Carries the machine-readable error id and the HTTP status to emit."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)