"""Error catalog: exact error ids and HTTP statuses from the scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_DUPLICATE_STUDY_CODE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_METHODOLOGY_IMMUTABLE": 409,
    "ERR_FACTOR_WEIGHT_INVALID": 422,
    "ERR_WEIGHT_SUM_MISMATCH": 422,
    "ERR_DUPLICATE_FRAME": 409,
    "ERR_UNKNOWN_FACTOR": 422,
    "ERR_FACTOR_COVERAGE_INCOMPLETE": 422,
    "ERR_SCORE_OUT_OF_RANGE": 422,
    "ERR_STUDY_NOT_FIELDING": 409,
    "ERR_FRAME_NOT_OPEN": 409,
    "ERR_NO_FRAMES": 409,
    "ERR_NO_RESPONSES": 409,
    "ERR_NO_SHORTFALL": 409,
    "ERR_NO_ELIGIBLE_BRAND": 409,
    "ERR_SOD_CONFLICT": 403,
    "ERR_EMBARGO_ACTIVE": 409,
    "ERR_AWARD_NOT_PUBLISHED": 409,
    "ERR_LICENSE_CONFLICT": 409,
    "ERR_LICENSE_TERM_INVALID": 422,
    "ERR_MARKETS_INVALID": 422,
    "ERR_LICENSE_NOT_EXPIRED": 409,
    "ERR_AUDITS_UNRESOLVED": 409,
    "ERR_SUBSCRIPTION_OVERLAP": 409,
    "ERR_SUBSCRIPTION_WINDOW_INVALID": 409,
    "ERR_SUBSCRIPTION_REQUIRED": 403,
    "ERR_TIER_INSUFFICIENT": 403,
    "ERR_RESULTS_NOT_PUBLISHED": 403,
}


def fail(error_id, message):
    raise ApiError(error_id, ERROR_STATUS[error_id], message)
