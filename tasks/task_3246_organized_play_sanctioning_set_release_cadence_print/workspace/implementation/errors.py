"""Error catalog (§1.6) for the Organized Play Sanctioning API."""


class ApiError(Exception):
    """Carries the error_id and HTTP status declared by the scaffold catalog."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else ERROR_STATUS.get(error_id, 400)


# id -> http status, verbatim from §1.6 of the scaffold / §5 of the PRD.
ERROR_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_INSUFFICIENT_POOL": 402,
    "ERR_PRINT_RUN_EXHAUSTED": 402,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REDEMPTION_CODE": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_REPORTING_WINDOW_OPEN": 409,
    "ERR_SET_NOT_STREET_LEGAL": 409,
    "ERR_PRIZE_REPORT_ALREADY_FILED": 409,
    "ERR_REPRINT_REVIEW_CLOSED": 409,
    "ERR_DUPLICATE_SET_CODE": 409,
    "ERR_DUPLICATE_JUDGE_REF": 409,
    "ERR_DUPLICATE_REDEMPTION_CODE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVITATION_REQUIRED": 422,
    "ERR_TIER_SLOT_CONFLICT": 422,
    "ERR_EVENT_WINDOW_OVERLAP": 422,
    "ERR_EVENT_SPACE_CAPACITY": 422,
    "ERR_FORMAT_CODE_NOT_LEGAL": 422,
    "ERR_REPRINT_MARKET_FLOOR": 422,
    "ERR_REPORT_WINDOW_CLOSED": 422,
    "ERR_STREET_DATE_BEFORE_PRERELEASE": 422,
    "ERR_HEADCOUNT_BELOW_THRESHOLD": 200,
}


def fail(error_id, message):
    raise ApiError(error_id, message)