"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_PARTICIPANT_SCOPE_VIOLATION": 403,
    # --- not found ---
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_AUTHORITY_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_TRANCHE_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_VESTING_EVENT_NOT_FOUND": 404,
    "ERR_TAX_ALLOCATION_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_PRECLEARANCE_NOT_FOUND": 404,
    "ERR_TRADING_PLAN_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    # --- request shape / pagination ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_EXERCISE_PRICE_MISMATCH": 400,
    # --- invalid state ---
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_AUTHORITY_INVALID_STATE": 409,
    "ERR_PARTICIPANT_INVALID_STATE": 409,
    "ERR_GRANT_INVALID_STATE": 409,
    "ERR_TRANCHE_INVALID_STATE": 409,
    "ERR_CYCLE_INVALID_STATE": 409,
    "ERR_VESTING_EVENT_INVALID_STATE": 409,
    "ERR_WINDOW_INVALID_STATE": 409,
    "ERR_PRECLEARANCE_INVALID_STATE": 409,
    "ERR_TRADING_PLAN_INVALID_STATE": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    # --- plan gates / concurrency ---
    "ERR_PLAN_FROZEN": 409,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_STALE_PARTICIPANT_VERSION": 412,
    # --- business safety ---
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RESERVE_INSUFFICIENT": 409,
    "ERR_BURN_RATE_LIMIT_EXCEEDED": 409,
    "ERR_AUTHORITY_NOT_EFFECTIVE": 409,
    "ERR_AUTHORITY_PER_GRANT_CAP_EXCEEDED": 409,
    "ERR_AUTHORITY_CAP_EXCEEDED": 409,
    "ERR_DELEGATED_APPROVAL_BLOCKED": 409,
    "ERR_MAX_GRANT_REVISIONS_EXCEEDED": 409,
    "ERR_MAX_PRECLEARANCE_REVISIONS_EXCEEDED": 409,
    "ERR_MAX_MODIFICATIONS_EXCEEDED": 409,
    "ERR_NO_ELIGIBLE_GRANT_DATE": 409,
    "ERR_PARTICIPANT_NOT_ACTIVE": 409,
    "ERR_ACCELERATION_FMV_REQUIRED": 409,
    "ERR_PERFORMANCE_NOT_CERTIFIED": 409,
    "ERR_TAX_ALLOCATION_MISSING": 409,
    "ERR_WORKDAY_COVERAGE_GAP": 409,
    "ERR_ASSIGNMENT_PERIOD_OVERLAP": 409,
    "ERR_TRADING_WINDOW_OVERLAP": 409,
    "ERR_TRADING_WINDOW_BUFFER_VIOLATION": 409,
    "ERR_TRADING_WINDOW_CLOSED": 409,
    "ERR_TRADE_DATE_OUTSIDE_WINDOW": 409,
    "ERR_WINDOW_SHARE_CAP_EXCEEDED": 409,
    "ERR_TRADING_PLAN_CONFLICT": 409,
    "ERR_COOLING_OFF_NOT_ELAPSED": 409,
    "ERR_PRECLEARANCE_EXPIRED": 409,
    "ERR_DUPLICATE_EMPLOYEE_NUMBER": 409,
    "ERR_DUPLICATE_METRIC_CODE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or unrecognised.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not perform this operation.",
    "ERR_PARTICIPANT_SCOPE_VIOLATION": "A participant may only reach their own records.",
    "ERR_INVALID_REQUEST": "The request body is malformed or fails a declared constraint.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are outside their permitted range.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def invalid(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
