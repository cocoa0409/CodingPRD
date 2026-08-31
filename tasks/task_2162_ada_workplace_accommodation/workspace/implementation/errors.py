"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ACTOR": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_A_PEOPLE_MANAGER": 403,
    "ERR_NOT_CASE_OWNER": 403,
    "ERR_MANAGER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_EMPLOYEE_NOT_FOUND": 404,
    "ERR_JOB_PROFILE_NOT_FOUND": 404,
    "ERR_ESSENTIAL_FUNCTION_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_DOC_REQUEST_NOT_FOUND": 404,
    "ERR_FUNCTION_ANALYSIS_NOT_FOUND": 404,
    "ERR_OPTION_NOT_FOUND": 404,
    "ERR_TRIAL_NOT_FOUND": 404,
    "ERR_DENIAL_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_ABSENCE_RECORD_NOT_FOUND": 404,
    "ERR_DUPLICATE_RESOURCE_KEY": 409,
    "ERR_PROFILE_NOT_DRAFT": 409,
    "ERR_PROFILE_NOT_PUBLISHED": 422,
    "ERR_INVALID_STAGE_TRANSITION": 409,
    "ERR_DOC_REQUEST_NOT_OPEN": 409,
    "ERR_OPTION_NOT_ASSESSABLE": 409,
    "ERR_TRIAL_NOT_RESOLVABLE": 409,
    "ERR_DENIAL_NOT_APPEALABLE": 409,
    "ERR_APPEAL_NOT_ACTIONABLE": 409,
    "ERR_ABSENCE_TRANSITION_INVALID": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CASE_SEALED": 409,
    "ERR_MEDICAL_SCOPE_OVERBROAD": 422,
    "ERR_DOCUMENTATION_NOT_PERMITTED": 422,
    "ERR_ESSENTIAL_FUNCTION_UNCOVERED": 422,
    "ERR_FUNCTION_NOT_IN_PINNED_PROFILE": 422,
    "ERR_DOC_REQUEST_LIMIT_EXCEEDED": 422,
    "ERR_FUNCTION_ANALYSIS_INCOMPLETE": 422,
    "ERR_NO_OPTIONS_PROPOSED": 422,
    "ERR_OPTION_ASSESSMENT_PENDING": 422,
    "ERR_DUPLICATE_FUNCTION_ANALYSIS": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_DOC_WINDOW_OVERLAP": 409,
    "ERR_TRIAL_WINDOW_CONFLICT": 409,
    "ERR_TRIAL_BLOCKED_BY_ABSENCE": 409,
    "ERR_INTERMITTENT_CAP_EXCEEDED": 422,
    "ERR_WC_MODIFIED_DUTY_REQUIRED": 409,
    "ERR_OPTION_HARDSHIP_BLOCKED": 422,
    "ERR_APPEAL_MUST_REMAND": 422,
    "ERR_APPEAL_SUPPLEMENT_LIMIT": 422,
    "ERR_INTERACTIVE_ROUND_LIMIT": 422,
    "ERR_INSUFFICIENT_TRIAL_REVIEWS": 422,
    "ERR_TRIAL_OUTCOME_MISMATCH": 422,
    "ERR_TRIAL_EXTENSION_LIMIT": 422,
    "ERR_OPEN_CASE_LIMIT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_CATALOG.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or invalid X-User-ID / X-User-Role headers.",
    "ERR_UNKNOWN_ACTOR": "X-User-ID does not resolve to an existing Employee.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role may not invoke this endpoint.",
    "ERR_NOT_A_PEOPLE_MANAGER": "The acting employee is not flagged as a people manager.",
    "ERR_NOT_CASE_OWNER": "The acting employee does not own this case.",
    "ERR_MANAGER_SCOPE_VIOLATION": "The acting manager is outside the department scope.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from acting on this appeal.",
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_STALE_VERSION": "The supplied concurrency token does not match the current version.",
    "ERR_CASE_SEALED": "The case is sealed; mutating operations are refused.",
}
