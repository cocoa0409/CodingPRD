"""Error catalogue (PRD 5) and the single exception the routes raise."""

ERROR_HTTP = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_UNAUTHORIZED_PHASE_ACTOR": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_FAMILY_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_CAPACITY_BLOCK_NOT_FOUND": 404,
    "ERR_PROMOTION_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_FORECAST_NOT_FOUND": 404,
    "ERR_ADJUSTMENT_NOT_FOUND": 404,
    "ERR_SUPPLY_PLAN_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_SCENARIO_NOT_FOUND": 404,
    "ERR_ACCURACY_RECORD_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_FORECAST_VERSION": 412,
    "ERR_STALE_CYCLE_VERSION": 412,
    # state / workflow
    "ERR_CYCLE_FROZEN": 409,
    "ERR_CYCLE_PHASE_CLOSED": 409,
    "ERR_CYCLE_TRANSITION_INVALID": 409,
    "ERR_FORECAST_TRANSITION_INVALID": 409,
    "ERR_ADJUSTMENT_NOT_REVIEWABLE": 409,
    "ERR_ADJUSTMENT_NOT_RESUBMITTABLE": 409,
    "ERR_ITEM_LIFECYCLE_TRANSITION_INVALID": 409,
    "ERR_SUPPLY_PLAN_NOT_RATIONABLE": 409,
    "ERR_SCENARIO_NOT_EVALUATABLE": 409,
    "ERR_SCENARIO_NOT_SELECTABLE": 409,
    "ERR_PROMOTION_NOT_APPROVABLE": 409,
    # business: referential eligibility
    "ERR_ITEM_NOT_PROMOTABLE": 422,
    "ERR_PROMOTION_NOT_APPROVED": 422,
    "ERR_ADJUSTMENT_TYPE_NOT_PERMITTED": 422,
    "ERR_SUCCESSOR_NOT_ELIGIBLE": 422,
    "ERR_FORECAST_NOT_LOCKED": 422,
    "ERR_OPEN_ADJUSTMENTS": 422,
    "ERR_STALE_SUPPLY_PLAN": 422,
    "ERR_UNEVALUATED_SCENARIO": 422,
    # business: temporal / interval
    "ERR_PROMOTION_WINDOW_OVERLAP": 409,
    "ERR_CAPACITY_BLOCK_OVERLAP": 409,
    "ERR_PROMOTION_HORIZON_FROZEN": 422,
    "ERR_MONTH_OUTSIDE_HORIZON": 422,
    # business: aggregate constraints and uniqueness
    "ERR_FAMILY_MONTHLY_HOURS_EXCEEDED": 422,
    "ERR_DUPLICATE_FORECAST": 409,
    "ERR_SUPPLY_PLAN_EXISTS": 409,
    "ERR_DUPLICATE_ACCURACY_RECORD": 409,
    # business: rate and volume safety limits
    "ERR_REOPEN_LIMIT_REACHED": 422,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_RUNOUT_INVENTORY_REMAINS": 422,
    # business: financial guardrails
    "ERR_ADJUSTMENT_SWING_EXCEEDED": 422,
    "ERR_UNCLOSED_GAP": 422,
    # fallback for unrouted requests
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)
