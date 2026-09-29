"""Error catalog (PRD section 5) and the single API exception type."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # existence
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_ROOM_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_PRESENTER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CHALLENGE_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_LOG_ENTRY_NOT_FOUND": 404,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_STALE_PARTICIPANT_VERSION": 412,
    # state preconditions
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_RESERVATION_STATE_INVALID": 409,
    "ERR_CONTRACT_STATE_INVALID": 409,
    "ERR_CHALLENGE_STATE_INVALID": 409,
    "ERR_SCREENING_STATE_INVALID": 409,
    "ERR_PRESENTER_SUSPENDED": 409,
    "ERR_PROGRAM_COMPLIANCE_BLOCKED": 409,
    "ERR_ROOM_OUT_OF_SERVICE": 409,
    "ERR_ROOM_DOUBLE_BOOKED": 409,
    "ERR_PRESENTER_DOUBLE_BOOKED": 409,
    # business: safety and compliance
    "ERR_PRESENTER_SCREENING_REQUIRED": 422,
    "ERR_PRESENTER_INSURANCE_LAPSED": 422,
    "ERR_PARTNER_INSURANCE_LAPSED": 422,
    "ERR_ACCESSIBILITY_UNSUPPORTED": 422,
    "ERR_SETUP_BUFFER_TOO_SHORT": 422,
    # business: temporal and referential
    "ERR_RESERVATION_WINDOW_MISMATCH": 422,
    "ERR_NO_CONFIRMED_ROOM": 422,
    "ERR_BRANCH_STAFFING_CAPACITY_EXCEEDED": 422,
    "ERR_INVALID_PROGRAM_WINDOW": 422,
    "ERR_PARTNER_FIELDS_REQUIRED": 422,
    # business: registration and attendance
    "ERR_DROP_IN_NO_REGISTRATION": 422,
    "ERR_REGISTRATION_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_REGISTRANT": 422,
    "ERR_PROGRAM_AT_CAPACITY": 422,
    # business: reading log
    "ERR_LOG_SOURCE_NOT_PERMITTED": 422,
    "ERR_LOG_DATE_OUTSIDE_WINDOW": 422,
    "ERR_LOG_DATE_IN_FUTURE": 422,
    "ERR_DAILY_LOG_CAP_EXCEEDED": 422,
    "ERR_CORRECTION_TARGET_INVALID": 422,
    "ERR_CORRECTION_WOULD_GO_NEGATIVE": 422,
    # business: challenge ladder
    "ERR_TIER_SEQUENCE_INVALID": 422,
    "ERR_CHALLENGE_HAS_NO_TIERS": 422,
    "ERR_CHALLENGE_WINDOW_STILL_OPEN": 422,
    # business: money
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_FEE_CAP_EXCEEDED": 422,
    "ERR_SUPPLY_INVENTORY_INSUFFICIENT": 422,
    "ERR_MATERIALS_BUDGET_EXCEEDED": 422,
    # business: close-out and closure
    "ERR_PROGRAM_NOT_YET_ENDED": 422,
    "ERR_ATTENDANCE_EXCEEDS_REGISTRATIONS": 422,
    "ERR_SURVEY_COUNT_EXCEEDS_ATTENDANCE": 422,
    "ERR_WEATHER_WINDOW_PASSED": 422,
    "ERR_BRANCH_CODE_DUPLICATE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Id and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "A Reader may only act on their own participant record.",
    "ERR_SEGREGATION_OF_DUTIES": "The user who issued the standing offer may not execute it.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in [1, 100] and offset an integer >= 0.",
    "ERR_STALE_PROGRAM_VERSION": "expected_program_version does not match the program's current version.",
    "ERR_STALE_PARTICIPANT_VERSION": "expected_participant_version does not match the participant's current version.",
}
