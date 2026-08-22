"""Error catalogue (PRD section 5) and the exception type carrying it."""

ERROR_STATUS = {
    # auth / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_OWNER_NOT_FOUND": 404,
    "ERR_TERRITORY_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_BILL_OF_SALE_NOT_FOUND": 404,
    "ERR_ESTRAY_CASE_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_REMITTANCE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # state
    "ERR_APPLICATION_INVALID_STATE": 409,
    "ERR_REGISTRATION_INVALID_STATE": 409,
    "ERR_CLAIM_INVALID_STATE": 409,
    "ERR_ORDER_NOT_SCHEDULABLE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_FEE_INVALID_STATE": 409,
    "ERR_ESTRAY_INVALID_STATE": 409,
    "ERR_INVESTIGATION_INVALID_STATE": 409,
    "ERR_REMITTANCE_INVALID_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_REGISTRATION_VERSION": 412,
    "ERR_STALE_INSPECTOR_VERSION": 412,
    # substantive board rules
    "ERR_BRAND_CONFLICT_EXISTS": 409,
    "ERR_ORDER_HOLD_ACTIVE": 409,
    "ERR_FACILITY_INTAKE_RESTRICTED": 409,
    "ERR_FACILITY_CAPACITY_EXCEEDED": 409,
    "ERR_INSPECTOR_UNAVAILABLE": 409,
    "ERR_INSPECTOR_WINDOW_CONFLICT": 409,
    "ERR_INSPECTOR_DAILY_LIMIT": 409,
    "ERR_TERRITORY_MISMATCH": 422,
    "ERR_HOLD_PERIOD_NOT_ELAPSED": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 409,
    "ERR_PRIOR_REGISTRATION_NOT_RENEWABLE": 422,
    "ERR_REGISTRATION_UNRENEWABLE": 422,
    "ERR_BILL_OF_SALE_MISMATCH": 422,
    "ERR_OWNER_STANDING_SUSPENDED": 402,
    "ERR_REMITTANCE_AMOUNT_INVALID": 422,
    "ERR_DUPLICATE_DOCUMENT_NUMBER": 409,
    "ERR_DUPLICATE_BADGE_NUMBER": 409,
    "ERR_DUPLICATE_TERRITORY_CODE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id.replace("ERR_", "").replace("_", " ").lower())


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or name an undeclared role.",
    "ERR_UNAUTHORIZED": "The acting role is not admitted to this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the targeted resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The recording operator must differ from the examining operator.",
    "ERR_INVALID_REQUEST": "The request body is malformed or violates a declared constraint.",
}
