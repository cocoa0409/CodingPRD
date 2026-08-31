"""Error catalogue (PRD section 5 / scaffold section 1.6)."""

ERROR_STATUS = {
    # authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # existence
    "ERR_BUSINESS_UNIT_NOT_FOUND": 404,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_CURRICULUM_NOT_FOUND": 404,
    "ERR_TRAINING_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_ASSOCIATION_NOT_FOUND": 404,
    "ERR_PARTICIPATION_NOT_FOUND": 404,
    "ERR_MEETING_NOT_FOUND": 404,
    "ERR_ATTENDANCE_NOT_FOUND": 404,
    "ERR_CONTACT_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_HSR_ANALYSIS_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_DRILL_NOT_FOUND": 404,
    "ERR_DOCUMENT_AUDIT_NOT_FOUND": 404,
    "ERR_LENIENCY_APPLICATION_NOT_FOUND": 404,
    "ERR_RISK_ASSESSMENT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_BUSINESS_UNIT_FROZEN": 409,
    "ERR_BUSINESS_UNIT_RESTRICTED": 409,
    "ERR_PARTICIPATION_NOT_ACTIVE": 409,
    "ERR_TRANSACTION_NOT_ANALYZED": 409,
    "ERR_MARKER_NOT_GRANTED": 409,
    "ERR_MARKER_ALREADY_HELD": 409,
    "ERR_WAITING_PERIOD_ACTIVE": 409,
    # business rules
    "ERR_RISK_BAND_TOO_LOW": 422,
    "ERR_TRAINING_NOT_CURRENT": 422,
    "ERR_CLEARANCE_NOT_GRANTED": 422,
    "ERR_ASSOCIATION_NOT_APPROVED": 422,
    "ERR_CURRICULUM_ROLE_MISMATCH": 422,
    "ERR_DUPLICATE_PARTICIPATION": 409,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_AGENDA_DEADLINE_MISSED": 422,
    "ERR_ATTENDEE_WINDOW_CONFLICT": 409,
    "ERR_SITE_DRILL_CAPACITY_EXCEEDED": 409,
    "ERR_REVIEW_MINUTES_EXCEEDED": 422,
    "ERR_EXPOSURE_BUDGET_EXCEEDED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
