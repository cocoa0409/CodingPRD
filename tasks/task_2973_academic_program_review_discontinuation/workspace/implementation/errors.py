"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication and authorization
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_INVALID_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_PROGRAM_OWNER": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_SELF_STUDY_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_GUARANTEE_NOT_FOUND": 404,
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    # payload shape
    "ERR_VALIDATION": 422,
    # optimistic concurrency
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_STALE_CYCLE_VERSION": 412,
    # state preconditions
    "ERR_PROGRAM_ALREADY_TERMINAL": 409,
    "ERR_CATALOG_TRANSITION_INVALID": 409,
    "ERR_SELF_STUDY_NOT_DRAFT": 409,
    "ERR_CYCLE_STATE_INVALID": 409,
    "ERR_VISIT_NOT_SCHEDULED": 409,
    "ERR_DECISION_STATE_INVALID": 409,
    "ERR_NOTIFICATION_STATE_INVALID": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_GUARANTEE_STATE_INVALID": 409,
    "ERR_STUDENT_STATE_INVALID": 409,
    "ERR_APPOINTMENT_STATE_INVALID": 409,
    # uniqueness and loop bounds
    "ERR_DUPLICATE_PROGRAM_CODE": 409,
    "ERR_DUPLICATE_TERM_SNAPSHOT": 409,
    "ERR_SELF_STUDY_ALREADY_EXISTS": 409,
    "ERR_OPEN_CYCLE_EXISTS": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_ADDENDUM_LIMIT_REACHED": 409,
    # self-study and review workflow
    "ERR_SELF_STUDY_WINDOW_CLOSED": 409,
    "ERR_SELF_STUDY_SECTIONS_INCOMPLETE": 422,
    "ERR_REVIEWER_CONFLICT_OF_INTEREST": 409,
    "ERR_REVIEWER_WINDOW_CONFLICT": 409,
    "ERR_PROGRAM_HOST_CAPACITY_EXCEEDED": 409,
    "ERR_VISIT_WINDOW_NOT_ELAPSED": 409,
    "ERR_REPORT_ALREADY_FILED": 409,
    "ERR_UNKNOWN_FINDING_CODE": 422,
    # decision, notification, consolidation
    "ERR_OUTCOME_NOT_SUPPORTED_BY_VIABILITY": 422,
    "ERR_RECEIVING_PROGRAM_REQUIRED": 422,
    "ERR_RECEIVING_PROGRAM_INELIGIBLE": 422,
    "ERR_AGENCY_NOTICE_NOT_ACKNOWLEDGED": 409,
    "ERR_TEACH_OUT_REQUIRED": 409,
    "ERR_SEVERANCE_CAP_EXCEEDED": 409,
    "ERR_TEACH_OUT_IN_EFFECT": 409,
    # teach-out, seats, advising
    "ERR_TEACH_OUT_HORIZON_INSUFFICIENT": 422,
    "ERR_COURSE_GUARANTEE_SHORTFALL": 409,
    "ERR_AT_RISK_STUDENTS_PRESENT": 409,
    "ERR_DECISION_NOT_EFFECTUATED": 409,
    "ERR_SEAT_CAPACITY_EXCEEDED": 409,
    "ERR_SEAT_NOT_COMMITTED": 409,
    "ERR_GUARANTEE_HAS_COMMITMENTS": 409,
    "ERR_ADVISING_REQUIRED": 409,
    # faculty and staffing
    "ERR_REDUCTION_SEQUENCE_VIOLATION": 409,
    "ERR_TENURE_NOTICE_TOO_SHORT": 422,
    "ERR_TENURE_OBLIGATION_ACTIVE": 409,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_REASSIGNMENT_TARGET_INVALID": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADER": "X-User-ID and X-User-Role are both required and must be non-blank.",
    "ERR_INVALID_ROLE": "X-User-Role does not name one of the six declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorised for this endpoint or does not own the requested action.",
    "ERR_NOT_PROGRAM_OWNER": "The acting program chair does not own the target program.",
    "ERR_NOT_ASSIGNED_REVIEWER": "The acting reviewer is not the reviewer assigned to this visit.",
    "ERR_SEGREGATION_OF_DUTIES": "A decision may not be ratified by the provost who proposed it.",
    "ERR_VALIDATION": "The request body does not conform to the endpoint's input schema.",
    "ERR_PROGRAM_ALREADY_TERMINAL": "The target program's lifecycle_state is terminal and closed to writes.",
    "ERR_CATALOG_TRANSITION_INVALID": "The requested catalog_status is not a declared edge from the current catalog_status.",
}


class ApiError(Exception):
    """Raised anywhere in a handler to abort with one catalogued error id."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def bad_request(error_id, message=None):
    raise ApiError(error_id, message)
