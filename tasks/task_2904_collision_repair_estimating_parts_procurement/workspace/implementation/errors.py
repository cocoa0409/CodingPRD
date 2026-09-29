"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# error_id -> http status, straight from PRD section 5
CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_WINDOW": 400,
    "ERR_REPAIR_ORDER_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_INSURER_NOT_FOUND": 404,
    "ERR_ESTIMATE_LINE_NOT_FOUND": 404,
    "ERR_DAMAGE_LINE_NOT_FOUND": 404,
    "ERR_SUPPLEMENT_NOT_FOUND": 404,
    "ERR_PARTS_VENDOR_NOT_FOUND": 404,
    "ERR_PARTS_LINE_NOT_FOUND": 404,
    "ERR_PROCEDURE_RECORD_NOT_FOUND": 404,
    "ERR_CALIBRATION_BAY_NOT_FOUND": 404,
    "ERR_STALL_NOT_FOUND": 404,
    "ERR_STAGE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STALE_REPAIR_ORDER_VERSION": 412,
    "ERR_ORDER_TERMINAL": 409,
    "ERR_STAGE_PRECONDITION": 409,
    "ERR_STAGE_SEQUENCE_INVALID": 409,
    "ERR_PARTS_LINE_STATE": 409,
    "ERR_AUTHORIZATION_POSTURE_BLOCKED": 409,
    "ERR_SUPPLEMENT_NOT_OPEN": 409,
    "ERR_CALIBRATION_STATE": 409,
    "ERR_ASSIGNMENT_NOT_SCHEDULED": 409,
    "ERR_CALIBRATION_NOT_VERIFIED": 422,
    "ERR_PROCEDURE_ADHERENCE_MISSING": 422,
    "ERR_ADAS_PROCEDURE_RESEARCH_MISSING": 422,
    "ERR_NOT_INCLUDED_JUSTIFICATION_MISSING": 422,
    "ERR_VENDOR_SUSPENDED": 422,
    "ERR_PART_TYPE_NOT_OFFERED": 422,
    "ERR_PART_TYPE_NOT_ALLOWED_BY_INSURER": 422,
    "ERR_STALL_TYPE_MISMATCH": 422,
    "ERR_BAY_TYPE_UNSUPPORTED": 422,
    "ERR_STALL_UNAVAILABLE": 422,
    "ERR_VENDOR_QTY_CAP_EXCEEDED": 422,
    "ERR_STALL_WINDOW_CONFLICT": 409,
    "ERR_CALIBRATION_BAY_CAPACITY_EXCEEDED": 409,
    "ERR_SUPPLEMENT_ROUND_LIMIT": 422,
    "ERR_NO_TEARDOWN_FINDINGS": 422,
    "ERR_NO_ESTIMATE_LINES": 422,
    "ERR_PARTS_NOT_PROCURED": 422,
    "ERR_PARTS_NOT_INSTALLED": 422,
    "ERR_NO_STAGE_ASSIGNMENT": 422,
    "ERR_INVALID_RETURN_QUANTITY": 422,
    "ERR_INVALID_RECEIVE_QUANTITY": 422,
    "ERR_COUNTER_NOT_LOWER": 422,
    "ERR_VENDOR_MISMATCH": 422,
    "ERR_CUSTOMER_CONSENT_REQUIRED": 422,
    "ERR_OEM_UPGRADE_NOT_APPLICABLE": 422,
    "ERR_QC_NOT_PASSED": 409,
    "ERR_OPEN_PARTS_DELAY": 409,
    "ERR_INVALID_PARTIAL_AMOUNT": 422,
    "ERR_SUPPLEMENT_REQUIRED": 422,
    "ERR_PARTS_PRICE_CEILING_EXCEEDED": 422,
    "ERR_VENDOR_SCORE_BELOW_FLOOR": 422,
    "ERR_AUTHORIZED_AMOUNT_EXCEEDED": 402,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not use this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting party does not own the addressed repair order.",
    "ERR_SEGREGATION_OF_DUTIES": "The estimator who blueprinted this order may not inspect it.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_ENUM_VALUE": "An enum-typed value is outside its declared members.",
    "ERR_INVALID_PAGINATION": "limit must be between 1 and 100 and offset must be >= 0.",
    "ERR_INVALID_WINDOW": "window_end must be strictly after window_start and both must be ISO-8601 instants.",
}


def raise_error(error_id, message=None):
    raise ApiError(error_id, CATALOG[error_id], message)
