"""Error classes and the error-id catalogue for the fertility-benefit API.

HTTP status values are pinned to the catalogue in PRD section 5.
"""


class APIError(Exception):
    """An error carrying the exact error_id and HTTP status the API returns."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)


# error_id -> HTTP status (PRD section 5, verbatim)
HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SOD_CONFLICT": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_EMPLOYER_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_ADVOCATE_NOT_FOUND": 404,
    "ERR_CLINIC_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_BUNDLE_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PREAUTH_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_OPERATION": 409,
    "ERR_NO_ADVOCATE_CANDIDATE": 422,
    "ERR_ADVOCATE_CREDENTIAL_LAPSED": 422,
    "ERR_CLINIC_NOT_CONTRACTED": 422,
    "ERR_CLINIC_CONTRACT_FROZEN": 422,
    "ERR_BENEFIT_INACTIVE": 422,
    "ERR_BUNDLE_EXHAUSTED": 422,
    "ERR_NO_REMAINING_ALLOWANCE": 422,
    "ERR_CLINICAL_CRITERIA_NOT_MET": 422,
    "ERR_SEQUENCE_OUT_OF_ORDER": 422,
    "ERR_SURRENDER_ROUTE_CONFLICT": 409,
    "ERR_CYCLE_SLOT_OVERLAP": 409,
    "ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE": 422,
    "ERR_BUNDLE_PRICE_UNPINNED": 422,
    "ERR_PHARMACY_POOL_EXHAUSTED": 422,
    "ERR_REVERSAL_WINDOW_CLOSED": 422,
    "ERR_AMENDMENT_WINDOW_CLOSED": 422,
    "ERR_DONOR_AGENCY_REQUIRED": 400,
    "ERR_SURROGACY_CARRIER_REQUIRED": 400,
    "ERR_PLAN_VERSION_STALE": 412,
    "ERR_PREAUTH_VERSION_STALE": 412,
    "ERR_CYCLE_VERSION_STALE": 412,
}


def bad_request(message="The request body is malformed."):
    return APIError("ERR_INVALID_REQUEST", message)


def not_found(message="A referenced resource does not resolve."):
    return APIError("ERR_NOT_FOUND", message)