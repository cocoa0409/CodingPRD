"""API error type and the complete error-id -> HTTP-status catalog.

The catalog is transcribed verbatim from PRD section 5 / SCAFFOLD section 1.6
so a raise site can never drift from the declared status code: `api_error`
looks the status up by id.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    # auth / envelope
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION_PARAMETERS": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_SOD_PROPOSER_CANNOT_ADOPT": 403,
    "ERR_SOD_IIC_CANNOT_CHAIR": 403,
    "ERR_SOD_IIC_ON_BOARD": 403,
    "ERR_NOT_ADDRESSEE": 403,
    "ERR_NOT_SITTING_MEMBER": 403,
    "ERR_CHAIRMAN_OWNERSHIP": 403,
    # existence
    "ERR_ACCIDENT_CASE_NOT_FOUND": 404,
    "ERR_LAUNCH_DECISION_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_PARTY_ORGANIZATION_NOT_FOUND": 404,
    "ERR_PARTY_DESIGNATION_NOT_FOUND": 404,
    "ERR_GROUP_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_FACTUAL_REPORT_NOT_FOUND": 404,
    "ERR_RECORDER_NOT_FOUND": 404,
    "ERR_SAFETY_RECOMMENDATION_NOT_FOUND": 404,
    "ERR_BOARD_MEETING_NOT_FOUND": 404,
    # state
    "ERR_CASE_NOT_SCREENING": 409,
    "ERR_CASE_ALREADY_LAUNCHED": 409,
    "ERR_DECISION_STATE_INVALID": 409,
    "ERR_INVESTIGATION_PHASE_INVALID": 409,
    "ERR_PHASE_GATE_UNSATISFIED": 409,
    "ERR_DOCKET_NOT_OPEN": 409,
    "ERR_DOCKET_STATE_INVALID": 409,
    "ERR_DESIGNATION_NOT_ACTIVE": 409,
    "ERR_GROUP_NOT_ACTIVE": 409,
    "ERR_SEAT_NOT_SEATED": 409,
    "ERR_RECORDER_STATE_INVALID": 409,
    "ERR_REPORT_STATE_INVALID": 409,
    "ERR_RECOMMENDATION_STATE_INVALID": 409,
    "ERR_MEETING_NOT_IN_SESSION": 409,
    "ERR_NO_VOTE_TO_RETRACT": 409,
    # business safety
    "ERR_RECORDER_READOUT_INCOMPLETE": 409,
    # duplicates
    "ERR_DUPLICATE_REPORT_NUMBER": 409,
    "ERR_DUPLICATE_DESIGNATION": 409,
    "ERR_DUPLICATE_SEAT": 409,
    # temporal conflicts
    "ERR_BENCH_WINDOW_CONFLICT": 409,
    "ERR_ROOM_WINDOW_CONFLICT": 409,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # domain constraints
    "ERR_LAUNCH_THRESHOLD_NOT_MET": 422,
    "ERR_PARTY_TYPE_EXCLUDED": 422,
    "ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION": 422,
    "ERR_GROUP_NOT_COMPLETABLE": 422,
    "ERR_DOCKET_INCOMPLETE": 422,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_UNACCEPTABLE_STREAK_INSUFFICIENT": 422,
    "ERR_WINDOW_IN_PAST": 422,
}


def api_error(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
