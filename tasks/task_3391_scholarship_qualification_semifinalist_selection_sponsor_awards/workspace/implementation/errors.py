"""Error type and the PRD section 5 error catalogue (id -> HTTP status)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_ENDORSEMENT_SCHOOL_MISMATCH": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CYCLE_NOT_ACCEPTING_ENTRIES": 409,
    "ERR_CYCLE_NOT_CLOSED_FOR_SCORING": 409,
    "ERR_CYCLE_POSTURE_INVALID": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_UNSCORED_ENTRIES_REMAIN": 409,
    "ERR_PENDING_APPLICATIONS_REMAIN": 409,
    "ERR_MATCHING_ALREADY_RUN": 409,
    "ERR_DUPLICATE_ENTRY": 409,
    "ERR_ENTRY_INELIGIBLE": 422,
    "ERR_ENTRY_NOT_SEMIFINALIST": 409,
    "ERR_APPLICATION_WINDOW_CLOSED": 422,
    "ERR_APPLICATION_INCOMPLETE": 422,
    "ERR_CONFIRMING_SCORE_BELOW_FLOOR": 422,
    "ERR_AGREEMENT_WINDOW_OVERLAP": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_POOL_BELOW_COMMITTED": 422,
    "ERR_AWARD_NOT_OFFERED": 409,
    "ERR_NOT_RENEWABLE": 409,
    "ERR_RENEWAL_ALREADY_EXISTS": 409,
    "ERR_RENEWAL_CRITERIA_UNMET": 422,
    "ERR_DISBURSEMENT_NOT_DUE": 422,
    "ERR_DISBURSEMENT_HELD": 409,
    "ERR_NOTIFICATION_EMBARGOED": 422,
    "ERR_NOTIFICATION_SEQUENCE_VIOLATION": 409,
    "ERR_PUBLICITY_WINDOW_TOO_EARLY": 422,
    "ERR_CLOCK_REGRESSION": 422,
}


def err(error_id, message):
    """Raise an ApiError with the catalogued HTTP status for the error id."""
    raise ApiError(error_id, message, ERROR_HTTP[error_id])
