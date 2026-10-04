"""Error catalog (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_FORBIDDEN_RESOURCE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_VALIDATION": 400,
    "ERR_LOAN_WINDOW_INVALID": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_BUILD_STAGE_INVALID": 409,
    "ERR_ARTIST_NOT_ACTIVE": 409,
    "ERR_SOD_ASSESSOR_IS_SUPERVISOR": 409,
    "ERR_AUTHENTICITY_BELOW_THRESHOLD": 422,
    "ERR_WOOD_NOT_CONDITIONED": 409,
    "ERR_WOOD_ALREADY_ALLOCATED": 409,
    "ERR_DUPLICATE_ENDORSEMENT": 409,
    "ERR_ENDORSEMENT_REQUIRED": 409,
    "ERR_TECHNICIAN_NOT_QUALIFIED": 409,
    "ERR_INSTRUMENT_NOT_ELIGIBLE": 409,
    "ERR_INSTRUMENT_NOT_BANK_ELIGIBLE": 409,
    "ERR_RESTORATION_ALREADY_OPEN": 409,
    "ERR_SEASONING_INCOMPLETE": 409,
    "ERR_LOAN_WINDOW_CONFLICT": 409,
    "ERR_TECHNICIAN_WINDOW_CONFLICT": 409,
    "ERR_REVIEW_NOT_DUE": 409,
    "ERR_PERFORMANCE_IN_FUTURE": 422,
    "ERR_CLOCK_REGRESSION": 422,
    "ERR_NO_ELIGIBLE_INSTRUMENT": 422,
}


def raise_err(error_id, message):
    status = ERROR_HTTP.get(error_id)
    if status is None:
        status = 500
    raise ApiError(error_id, status, message)
