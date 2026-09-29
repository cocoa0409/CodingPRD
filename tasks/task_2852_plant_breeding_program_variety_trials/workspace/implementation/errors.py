"""Error catalogue (PRD section 5 / scaffold 1.6)."""

ERROR_HTTP = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_PROGRAM_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_OBJECTIVE_NOT_FOUND": 404,
    "ERR_NURSERY_BLOCK_NOT_FOUND": 404,
    "ERR_CROSSING_BLOCK_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_PLANTING_NOT_FOUND": 404,
    "ERR_TRIAL_SITE_NOT_FOUND": 404,
    "ERR_TRIAL_SERIES_NOT_FOUND": 404,
    "ERR_TRIAL_ENTRY_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_SEED_LOT_NOT_FOUND": 404,
    "ERR_BACKCROSS_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_LINE_VERSION": 412,
    "ERR_STALE_SERIES_VERSION": 412,
    # state
    "ERR_PROGRAM_CLOSED": 409,
    "ERR_PLANTING_INVALID_STATE": 409,
    "ERR_SERIES_INVALID_STATE": 409,
    "ERR_ENTRY_INVALID_STATE": 409,
    "ERR_AGREEMENT_INVALID_STATE": 409,
    "ERR_LOT_INVALID_STATE": 409,
    "ERR_PROJECT_NOT_ACTIVE": 409,
    "ERR_LINE_DISCARDED": 409,
    "ERR_BLOCK_NOT_POLLINATED": 409,
    # regulatory / stewardship
    "ERR_STEWARDSHIP_NOT_APPROVED": 422,
    "ERR_STEWARDSHIP_SUSPENDED": 409,
    "ERR_MARKET_NOT_IN_AGREEMENT": 422,
    # referential
    "ERR_OBJECTIVE_PROGRAM_MISMATCH": 422,
    "ERR_PARENT_LINE_PROGRAM_MISMATCH": 422,
    # capacity posture
    "ERR_SITE_CAPACITY_FROZEN": 409,
    "ERR_SITE_RESTRICTED_STAGE": 409,
    # temporal
    "ERR_BLOCK_OCCUPANCY_CONFLICT": 409,
    "ERR_NURSERY_SEASON_MISMATCH": 422,
    "ERR_SOW_DATE_IN_PAST": 422,
    "ERR_ENTRY_WINDOW_OUTSIDE_SEASON": 422,
    "ERR_AGREEMENT_DATES_INVALID": 422,
    # business constraints
    "ERR_DUPLICATE_TRIAL_ENTRY": 409,
    "ERR_PLOT_COUNT_NOT_DIVISIBLE": 422,
    "ERR_DUPLICATE_OBSERVATION": 409,
    "ERR_INSUFFICIENT_REPLICATION": 422,
    "ERR_INSUFFICIENT_LOCATIONS": 422,
    "ERR_EMPTY_BALANCED_CORE": 422,
    "ERR_NO_TRIAL_DATA": 422,
    "ERR_LINE_NOT_READY": 422,
    "ERR_INDEX_BELOW_THRESHOLD": 422,
    "ERR_AGREEMENT_ALREADY_ACTIVE": 409,
    "ERR_DUPLICATE_CODE": 409,
    # fiscal / capacity
    "ERR_BLOCK_PLOT_COUNT_EXCEEDED": 422,
    "ERR_SITE_PLOT_CAPACITY_EXCEEDED": 409,
    "ERR_PROGRAM_PLOT_BUDGET_EXCEEDED": 409,
    "ERR_PROGRAM_BUDGET_USD_EXCEEDED": 409,
    "ERR_INSUFFICIENT_SEED_INVENTORY": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def bad_request(message="The request is malformed or violates a field constraint."):
    raise ApiError("ERR_INVALID_REQUEST", message)
