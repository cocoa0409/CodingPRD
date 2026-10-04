"""Error carrier + the §5 error catalogue (error_id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_MIC_REQUIRED": 403,
    "ERR_OFFICE_SCOPE_VIOLATION": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_STORM_EVENT_NOT_FOUND": 404,
    "ERR_ZONE_NOT_FOUND": 404,
    "ERR_OFFICE_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_COORDINATION_REQUEST_NOT_FOUND": 404,
    "ERR_VERIFICATION_EVENT_NOT_FOUND": 404,
    "ERR_EMERGENCY_ACTION_NOT_FOUND": 404,
    "ERR_DISSEMINATION_RECORD_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_PRODUCT_STATE": 409,
    "ERR_INVALID_COORDINATION_STATE": 409,
    "ERR_INVALID_EVENT_STATE": 409,
    "ERR_INVALID_EM_ACTION_STATE": 409,
    "ERR_INVALID_STORM_STATE": 409,
    "ERR_RECORD_NOT_SETTLABLE": 409,
    "ERR_COORDINATION_NOT_ACKED": 409,
    "ERR_ISSUANCE_CRITERIA_NOT_MET": 422,
    "ERR_POLYGON_INVALID": 422,
    "ERR_WINDOW_INVALID": 422,
    "ERR_DURATION_OUT_OF_RANGE": 422,
    "ERR_EFFECTIVE_IN_PAST": 422,
    "ERR_PRODUCT_OVERLAP_CONFLICT": 409,
    "ERR_EVACUATION_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_AGREEMENT": 409,
    "ERR_INVALID_SUPERSEDE_CHAIN": 422,
    "ERR_MESSAGE_FORMAT_OVERFLOW": 422,
    "ERR_ZONE_OUTSIDE_CWA": 422,
    "ERR_POLYGON_OUTSIDE_CWA": 422,
    "ERR_ZONE_NOT_COVERED_BY_PRODUCT": 422,
}


def api_error(error_id, message):
    """Build an ApiError carrying the catalogue HTTP status for error_id."""
    return ApiError(error_id, ERROR_HTTP[error_id], message)
