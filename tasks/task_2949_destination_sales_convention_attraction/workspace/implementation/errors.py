"""Error catalogue (PRD section 5) and the ApiError exception."""


ERROR_HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VALIDATION": 400,
    # existence
    "ERR_PLANNER_NOT_FOUND": 404,
    "ERR_HOTEL_NOT_FOUND": 404,
    "ERR_HALL_NOT_FOUND": 404,
    "ERR_OPPORTUNITY_NOT_FOUND": 404,
    "ERR_SPACE_HOLD_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_BID_PACKAGE_NOT_FOUND": 404,
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_SERVICING_ORDER_NOT_FOUND": 404,
    "ERR_BOARD_REPORT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_OPPORTUNITY_VERSION": 412,
    "ERR_STALE_FUND_VERSION": 412,
    # state preconditions
    "ERR_INVALID_OPPORTUNITY_STAGE": 409,
    "ERR_INVALID_HOLD_STATE": 409,
    "ERR_INVALID_COMMITMENT_STATE": 409,
    "ERR_INVALID_BID_STATE": 409,
    "ERR_INVALID_SERVICING_STATE": 409,
    "ERR_BOARD_REPORT_PUBLISHED": 409,
    # safety / compliance
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_HALL_UNAVAILABLE": 409,
    "ERR_HOTEL_NOT_PARTICIPATING": 409,
    # temporal
    "ERR_LEAD_TIME_TOO_SHORT": 422,
    "ERR_HOLD_EXPIRED": 409,
    "ERR_CHALLENGE_WINDOW_CLOSED": 422,
    "ERR_HALL_WINDOW_CONFLICT": 409,
    "ERR_HALL_HOLD_LIMIT_REACHED": 409,
    "ERR_PICKUP_NIGHT_OUT_OF_RANGE": 422,
    "ERR_DUPLICATE_PICKUP_NIGHT": 422,
    "ERR_CUTOFF_MISALIGNED": 422,
    # constraint satisfaction
    "ERR_CHALLENGE_TARGET_INVALID": 422,
    "ERR_HALL_CAPACITY_INSUFFICIENT": 422,
    "ERR_DUPLICATE_COMMITMENT": 409,
    "ERR_RATE_CEILING_EXCEEDED": 422,
    "ERR_HOTEL_CAPACITY_EXCEEDED": 422,
    "ERR_NO_ACTIVE_SPACE_HOLD": 422,
    "ERR_SUPPORT_LETTERS_INSUFFICIENT": 422,
    "ERR_BLOCK_COVERAGE_INSUFFICIENT": 422,
    "ERR_BID_ROUND_LIMIT_REACHED": 409,
    "ERR_ESTIMATE_VARIANT_NOT_AVAILABLE": 422,
    # fiscal
    "ERR_FUND_EXHAUSTED": 409,
    "ERR_INCENTIVE_EXCEEDS_CAP": 422,
    "ERR_FUND_INSUFFICIENT": 422,
    "ERR_TAX_PAYBACK_BELOW_FLOOR": 422,
    # transport-level fallbacks (not part of the PRD catalogue)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}


class ApiError(Exception):
    """Raised anywhere in a request to abort it with a catalogued error."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)
        super().__init__(self.message)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def bad_request(message):
    return ApiError("ERR_VALIDATION", message)
