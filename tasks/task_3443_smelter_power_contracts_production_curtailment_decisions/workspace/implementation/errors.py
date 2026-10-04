"""Error catalog (PRD section 5). Every error_id raised anywhere lives here."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_POTLINE_INVALID_STATE": 409,
    "ERR_DECISION_INVALID_STATE": 409,
    "ERR_RESTART_PLAN_INVALID_STATE": 409,
    "ERR_INVALID_LIFECYCLE_STATE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PERMIT_NOT_ACTIVE": 409,
    "ERR_LABOR_AGREEMENT_INACTIVE": 409,
    "ERR_LABOR_NOTICE_PERIOD": 422,
    "ERR_CONTRACT_WINDOW_OVERLAP": 409,
    "ERR_CURTAILMENT_DEPTH_INVALID": 422,
    "ERR_INTERRUPTIBLE_CAP_EXCEEDED": 422,
    "ERR_PRODUCT_MIX_OVER_CAPACITY": 422,
    "ERR_PERMIT_DUPLICATE_TYPE": 409,
    "ERR_LABOR_AGREEMENT_EXISTS": 409,
    "ERR_RESTART_PLAN_EXISTS": 409,
    "ERR_NO_ACTIVE_POWER_CONTRACT": 422,
    "ERR_NO_PRICE_OBSERVATION": 422,
    "ERR_HEDGE_VOLUME_EXCEEDS_EXPOSURE": 422,
    "ERR_HEDGE_COVERAGE_INSUFFICIENT": 422,
}


def raise_err(error_id, message):
    """Raise an ApiError; KeyError here would mean the catalog is incomplete."""
    raise ApiError(error_id, message, ERROR_CATALOG[error_id])
