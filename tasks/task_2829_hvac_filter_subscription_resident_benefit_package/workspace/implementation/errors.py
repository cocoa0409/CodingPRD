"""Error catalogue (PRD section 5). error_id -> HTTP status."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_RESIDENT_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_ENTITLEMENT_NOT_FOUND": 404,
    "ERR_STALE_SUBSCRIPTION_VERSION": 412,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_PROPERTY_NOT_ACTIVE": 409,
    "ERR_SUBSCRIPTION_STATE_INVALID": 409,
    "ERR_SHIPMENT_STATE_INVALID": 409,
    "ERR_CLAIM_STATE_INVALID": 409,
    "ERR_CASE_STATE_INVALID": 409,
    "ERR_TRANSFER_STATE_INVALID": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_EVIDENCE_BELOW_CONFIRM_THRESHOLD": 422,
    "ERR_NO_EVIDENCE_FOR_METHOD": 422,
    "ERR_BENEFIT_NOT_ENTITLED": 422,
    "ERR_OUTSIDE_COVERAGE_WINDOW": 422,
    "ERR_SKU_DISCONTINUED": 422,
    "ERR_NO_ELIGIBLE_SKU": 422,
    "ERR_DUPLICATE_ACTIVE_SUBSCRIPTION": 409,
    "ERR_UNIT_OCCUPANCY_CONFLICT": 409,
    "ERR_SHIPMENT_WINDOW_OVERLAP": 409,
    "ERR_INFO_REQUEST_LIMIT": 422,
    "ERR_TRANSFER_DATE_INVALID": 422,
    "ERR_TRANSFER_TARGET_INVALID": 422,
    "ERR_CANCEL_DATE_INVALID": 422,
    "ERR_INVALID_RUNTIME_WINDOW": 422,
    "ERR_CLAIM_AMOUNT_EXCEEDS_CAP": 422,
    "ERR_PROPERTY_CREDIT_LIMIT_EXCEEDED": 402,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required",
    "ERR_ROLE_NOT_PERMITTED": "the acting role is not authorized for this endpoint",
    "ERR_NOT_RESOURCE_OWNER": "the acting principal does not own the target resource",
    "ERR_INVALID_REQUEST": "the request body is invalid",
    "ERR_INVALID_PAGINATION": "invalid pagination or filter query parameters",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower()
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
