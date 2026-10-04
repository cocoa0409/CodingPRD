"""Error catalog: exception class and HTTP status per error id (SCAFFOLD 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TITLE_NOT_OPEN": 409,
    "ERR_EMBARGO_ACTIVE": 409,
    "ERR_CRITIC_NOT_ACCREDITED": 409,
    "ERR_PUBLICATION_NOT_ACCREDITED": 409,
    "ERR_DUPLICATE_REVIEW": 409,
    "ERR_VERIFICATION_WINDOW_MISS": 409,
    "ERR_TICKET_NOT_VERIFIED": 409,
    "ERR_DUPLICATE_VERIFIED_RATING": 409,
    "ERR_BOMBING_SUSPENSION_ACTIVE": 409,
    "ERR_ACC_REVIEW_PERIOD_OVERLAP": 409,
    "ERR_DISPUTE_ALREADY_TERMINAL": 409,
    "ERR_INVALID_RECLASSIFICATION": 400,
    "ERR_SELF_DISPUTE_FORBIDDEN": 409,
    "ERR_SCORE_NOT_COMPUTABLE": 409,
}


def err(error_id, message):
    return ApiError(error_id, message, HTTP_STATUS[error_id])
