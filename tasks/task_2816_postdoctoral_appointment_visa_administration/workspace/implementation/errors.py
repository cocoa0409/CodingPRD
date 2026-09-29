"""Error catalog and the ApiError exception (PRD section 5)."""

ERROR_HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_POSTDOC_NOT_FOUND": 404,
    "ERR_MENTOR_NOT_FOUND": 404,
    "ERR_FUNDING_SOURCE_NOT_FOUND": 404,
    "ERR_LABORATORY_NOT_FOUND": 404,
    "ERR_APPOINTMENT_NOT_FOUND": 404,
    "ERR_VISA_CASE_NOT_FOUND": 404,
    "ERR_DEVELOPMENT_DOCUMENT_NOT_FOUND": 404,
    "ERR_EXPORT_REVIEW_NOT_FOUND": 404,
    "ERR_LAB_GRANT_NOT_FOUND": 404,
    "ERR_REAPPOINTMENT_REVIEW_NOT_FOUND": 404,
    "ERR_GRIEVANCE_NOT_FOUND": 404,
    "ERR_EXIT_RECORD_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # state / concurrency
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_APPOINTMENT_VERSION": 412,
    "ERR_REVIEW_ALREADY_OPEN": 409,
    "ERR_EXIT_ALREADY_INITIATED": 409,
    # research security
    "ERR_EXPORT_CONTROL_BLOCKED": 422,
    "ERR_COMPLIANCE_RESTRICTION_VIOLATED": 422,
    "ERR_LAB_CLOSED": 409,
    # referential / configuration integrity
    "ERR_FUNDING_NOT_VERIFIED": 422,
    "ERR_AWARD_EXPIRED": 422,
    "ERR_AWARD_TERM_NO_OVERLAP": 422,
    "ERR_FUNDING_CLASS_MISMATCH": 422,
    "ERR_TITLE_CLASS_MISMATCH": 422,
    "ERR_MENTOR_TRAINING_LAPSED": 422,
    "ERR_NO_ELIGIBLE_VISA_CATEGORY": 422,
    # constraint
    "ERR_RANK_YEARS_EXCEEDED": 422,
    "ERR_TERM_LENGTH_INVALID": 422,
    "ERR_PREMIUM_TRACK_UNAVAILABLE": 422,
    "ERR_RFE_ROUND_LIMIT_REACHED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_DEVELOPMENT_DOCS_INCOMPLETE": 422,
    "ERR_IDP_NOT_ACKNOWLEDGED": 422,
    "ERR_VISA_NOT_APPROVED": 422,
    "ERR_LAB_CAPACITY_EXCEEDED": 409,
    "ERR_MENTOR_LOAD_EXCEEDED": 409,
    # temporal
    "ERR_START_BEFORE_LAWFUL_DATE": 422,
    "ERR_APPOINTMENT_TERM_OVERLAP": 409,
    "ERR_GRIEVANCE_WINDOW_CLOSED": 422,
    "ERR_LAB_BUFFER_CONFLICT": 409,
    # fiscal
    "ERR_SALARY_BELOW_FLOOR": 422,
    "ERR_EXCEPTION_FLOOR_INVALID": 422,
    "ERR_FUNDING_BUDGET_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the declared role is not recognised.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this user from performing this action.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_STATE_TRANSITION": "The target record does not declare the requested transition from its current state.",
    "ERR_STALE_APPOINTMENT_VERSION": "expected_appointment_version does not match the appointment's current version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
