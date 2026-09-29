"""Error catalogue (PRD section 5 / scaffold section 1.6).

Every error_id maps to exactly one HTTP status.  Handlers raise ApiError with an
error_id from this table; the HTTP status is looked up here so a route can never
pair an id with the wrong status.
"""

ERROR_STATUS = {
    # auth / identity
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ENTRY_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # schema
    "ERR_INVALID_REQUEST": 422,
    # existence
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_COURSE_NOT_FOUND": 404,
    "ERR_OBSTACLE_NOT_FOUND": 404,
    "ERR_DIVISION_NOT_FOUND": 404,
    "ERR_WAVE_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_ATTEMPT_NOT_FOUND": 404,
    "ERR_STAFF_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RESTORATION_TASK_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_ENTRY_VERSION": 412,
    "ERR_STALE_VENUE_VERSION": 412,
    # state
    "ERR_PERMIT_STATE_INVALID": 409,
    "ERR_PERMIT_ALREADY_APPROVED": 409,
    "ERR_COURSE_STATE_INVALID": 409,
    "ERR_OBSTACLE_SET_FROZEN": 409,
    "ERR_VENUE_FROZEN": 409,
    "ERR_WAVE_NOT_RELEASABLE": 409,
    "ERR_WAVE_ROSTER_NOT_LOCKED": 409,
    "ERR_ROSTER_CLOSED": 409,
    "ERR_WAVE_STATE_INVALID": 409,
    "ERR_ENTRY_STATE_INVALID": 409,
    "ERR_ENTRY_NOT_PROTESTABLE": 409,
    "ERR_PROTEST_ROUNDS_EXHAUSTED": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_TASK_STATE_INVALID": 409,
    "ERR_BOND_ALREADY_SETTLED": 409,
    # business: referential / cross-entity
    "ERR_COURSE_NOT_PUBLISHED": 409,
    "ERR_WAVE_COURSE_MISMATCH": 409,
    "ERR_DIVISION_RULE_VIOLATION": 409,
    "ERR_BYPASS_NOT_ALLOWED": 409,
    "ERR_TEAM_INCOMPLETE": 409,
    # business: safety
    "ERR_MEDICAL_COVERAGE_INSUFFICIENT": 409,
    "ERR_COURSE_UNSAFE": 409,
    "ERR_WAIVER_REQUIRED": 409,
    "ERR_PARTICIPANT_NOT_CLEARED": 409,
    "ERR_OBSTACLE_UNMARSHALED": 409,
    "ERR_OBSTACLE_MARSHALED": 409,
    # business: temporal
    "ERR_QUIET_HOURS_VIOLATION": 409,
    "ERR_STAFF_SHIFT_CONFLICT": 409,
    "ERR_CORRAL_WINDOW_CONFLICT": 409,
    # business: uniqueness / constraint
    "ERR_STATION_INDEX_CONFLICT": 409,
    "ERR_BIB_NUMBER_TAKEN": 409,
    "ERR_UNIQUENESS_CONFLICT": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_WATER_USE_NOT_PERMITTED": 409,
    "ERR_COURSE_TOO_SHORT": 422,
    "ERR_PROGRESSION_TOO_FLAT": 422,
    "ERR_PROGRESSION_REGRESSION": 422,
    "ERR_AGE_INELIGIBLE": 409,
    "ERR_RESTORATION_AREA_EXCEEDED": 409,
    "ERR_RESTORATION_INCOMPLETE": 409,
    # business: fiscal / capacity
    "ERR_DISTURBED_AREA_EXCEEDED": 409,
    "ERR_DESIGN_CAPACITY_EXCEEDED": 409,
    "ERR_WAVE_CAPACITY_EXCEEDED": 409,
    "ERR_BOTTLENECK_CAPACITY_EXCEEDED": 409,
    "ERR_WAVE_ROSTER_EMPTY": 409,
    # fallback for unroutable requests
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    """Raised anywhere in a handler; converted to the error envelope by app.py."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)
