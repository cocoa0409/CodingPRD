"""Error identifiers and the ApiError exception type.

Every error_id below is copied verbatim from the scaffold error catalogue
(SCAFFOLD.yaml §1.6) together with its HTTP status.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=400, detail=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status
        self.detail = detail
        self.error_detail = detail


# --- error id -> http status (scaffold §1.6, verbatim) -----------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_AGENCY_NOT_OF_RECORD": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_WRITE_FROZEN": 409,
    "ERR_RISK_ZONE_FROZEN": 409,
    "ERR_POSTURE_REFERRAL_REQUIRED": 409,
    "ERR_AGENCY_INACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ENROLLMENT_NOT_BOUND": 409,
    "ERR_CONSULTATION_SLOT_CONFLICT": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_NOTICE_PERIOD_INSUFFICIENT": 422,
    "ERR_MITIGATION_LAPSED": 422,
    "ERR_SCHEDULED_VALUE_CAP": 422,
    "ERR_COVERAGE_ABOVE_APPRAISAL": 422,
    "ERR_COVERAGE_BELOW_REQUIRED": 422,
    "ERR_GROUND_NOT_ACTIONABLE": 422,
    "ERR_VALUATION_STALE": 422,
    "ERR_APPRAISAL_DOC_MISMATCH": 422,
    "ERR_APPRAISAL_CURRENCY_EXPIRED": 422,
    "ERR_ZONE_EVENT_INACTIVE": 422,
    "ERR_NO_ELIGIBLE_VENDOR": 422,
    "ERR_APPRAISAL_PROVISION_BASELINE": 422,
    "ERR_APPRAISAL_METHOD_INVALID": 422,
    "ERR_BRANCH_CAPITAL_INSUFFICIENT": 422,
    "ERR_CLAIM_BELOW_DEDUCTIBLE": 422,
    "ERR_INCOMPATIBLE_ENDORSEMENT": 422,
    "ERR_ZONE_DISPATCH_CAPACITY": 422,
    "ERR_INVALID_REQUEST": 400,
}


def err(error_id, message="", detail=None):
    """Build an ApiError with the scaffold-defined status for its error_id."""
    return ApiError(error_id, message, ERROR_STATUS.get(error_id, 400), detail)