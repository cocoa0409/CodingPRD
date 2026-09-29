"""Error catalogue for the Public Records & Data Journalism Desk API (PRD section 5)."""

# error_id -> HTTP status
ERROR_STATUS = {
    # --- authentication / authorization ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ASSIGNMENT_NOT_OWNED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- existence ---
    "ERR_DESK_NOT_FOUND": 404,
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_REQUEST_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_DATASET_NOT_FOUND": 404,
    "ERR_FIELD_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SUBJECT_REQUEST_NOT_FOUND": 404,
    "ERR_ENCLAVE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    # --- optimistic concurrency ---
    "ERR_STALE_DESK_VERSION": 412,
    "ERR_STALE_INVESTIGATION_VERSION": 412,
    # --- state gates ---
    "ERR_INVALID_REQUEST_STATE": 409,
    "ERR_INVALID_APPEAL_STATE": 409,
    "ERR_INVALID_DATASET_STATE": 409,
    "ERR_INVALID_INVESTIGATION_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_FINDING_STATE": 409,
    "ERR_INVALID_SUBJECT_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_SUPERSEDE_TARGET_NOT_ACTIVE": 409,
    "ERR_FEE_ALREADY_DETERMINED": 409,
    # --- business rules ---
    "ERR_TOLLING_NOT_PERMITTED": 422,
    "ERR_CLARIFICATION_LIMIT_REACHED": 409,
    "ERR_APPEAL_NOT_RIPE": 409,
    "ERR_APPEAL_VENUE_MISMATCH": 422,
    "ERR_FEE_BUDGET_EXCEEDED": 402,
    "ERR_DESK_LOCKDOWN": 409,
    "ERR_INVESTIGATION_NOT_CLEARED": 409,
    "ERR_SOURCE_REQUEST_UNRESOLVED": 409,
    "ERR_RELEASE_DATASET_REQUIRED": 422,
    "ERR_DATASET_NOT_LINKED": 422,
    "ERR_SOURCE_EXPOSURE_RISK": 422,
    "ERR_DISCLOSURE_RISK_TOO_HIGH": 422,
    "ERR_REVIEWER_CONFLICT_OF_INTEREST": 422,
    "ERR_REVIEWER_CAPACITY_EXCEEDED": 409,
    "ERR_SUBJECT_NOTICE_PENDING": 409,
    "ERR_INSUFFICIENT_NOTICE": 422,
    "ERR_INSUFFICIENT_ATTEMPTS": 422,
    "ERR_ENCLAVE_SESSION_OVERLAP": 409,
    "ERR_ENCLAVE_DOCUMENT_LIMIT": 409,
    "ERR_NO_ALLOCABLE_INPUTS": 422,
    "ERR_ANALYSIS_NOT_READY": 409,
    "ERR_DATASET_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_FORMAT_NOT_NEGOTIATED": 422,
    "ERR_DATASET_NAME_CONFLICT": 409,
    "ERR_FIELD_NAME_CONFLICT": 409,
    "ERR_FIELD_LIMIT_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unrecognized role.",
    "ERR_ROLE_NOT_PERMITTED": "The authenticated role is not permitted to perform this operation.",
    "ERR_ASSIGNMENT_NOT_OWNED": "The assignment is not owned by the calling expert reviewer.",
    "ERR_SEGREGATION_OF_DUTIES": "The author of an analysis run may not peer review it.",
    "ERR_INVALID_REQUEST": "The request payload or query string failed validation.",
    "ERR_FEE_BUDGET_EXCEEDED": "The commit exceeds the desk's available fee budget.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id) or error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)


def error_count():
    return len(ERROR_STATUS)
