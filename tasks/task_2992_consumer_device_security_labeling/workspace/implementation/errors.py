"""Error catalogue and the ApiError exception (PRD section 5)."""


ERROR_HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROGRAM_CONFIG_NOT_FOUND": 404,
    "ERR_MANUFACTURER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CRITERION_NOT_FOUND": 404,
    "ERR_TEST_LAB_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_REGISTRY_CODE_NOT_FOUND": 404,
    # state
    "ERR_INVALID_ASSESSMENT_STATE": 409,
    "ERR_INVALID_GRANT_STATE": 409,
    "ERR_INVALID_ENGAGEMENT_STATE": 409,
    "ERR_INVALID_CASE_STATE": 409,
    "ERR_INVALID_AUTHORIZATION_STATE": 409,
    "ERR_PENALTY_NOT_ASSESSED": 409,
    # optimistic concurrency
    "ERR_STALE_PRODUCT_VERSION": 412,
    "ERR_STALE_GRANT_VERSION": 412,
    # eligibility scope and conformance
    "ERR_DEVICE_CLASS_EXCLUDED": 422,
    "ERR_PRACTICE_AREA_UNCOVERED": 422,
    "ERR_THIRD_PARTY_TEST_REQUIRED": 422,
    "ERR_SCORE_BELOW_MINIMUM": 422,
    "ERR_DUPLICATE_CRITERION_RESPONSE": 409,
    # label issuance and renewal
    "ERR_ASSESSMENT_PRODUCT_MISMATCH": 422,
    "ERR_ASSESSMENT_NOT_APPROVED": 409,
    "ERR_ASSESSMENT_SPEC_STALE": 422,
    "ERR_SPONSOR_DELINQUENT": 402,
    # registry content and support period
    "ERR_REGISTRY_DISCLOSURE_INCOMPLETE": 422,
    "ERR_SUPPORT_PERIOD_TOO_SHORT": 422,
    "ERR_SUPPORT_PERIOD_EXPIRED": 422,
    # lab capacity
    "ERR_LAB_NOT_ACCREDITED": 422,
    "ERR_LAB_BENCH_CAPACITY_CONFLICT": 409,
    "ERR_LAB_BENCH_HOURS_EXCEEDED": 409,
    # retailer display
    "ERR_GRANT_NOT_PUBLISHED": 409,
    "ERR_EDUCATION_ACK_REQUIRED": 422,
    "ERR_DISPLAY_WINDOW_OUTSIDE_VALIDITY": 422,
    "ERR_DISPLAY_WINDOW_CONFLICT": 409,
    # enforcement
    "ERR_LABEL_LEGITIMATELY_ISSUED": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with an error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
