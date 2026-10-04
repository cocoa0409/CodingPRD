"""Error catalog and ApiError type.

HTTP statuses come from PRD section 5 (error catalogue). ERR_STANDARD_STATE_INVALID
is named by PRD section 3.7 (and the scaffold state machine) but is absent from the
section 5 table; it is a state-gate error, so it carries 409 like every other
state-gate error.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_VALIDATION": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_GOVERNMENT_NOT_FOUND": 404,
    "ERR_MEMBER_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_CYCLE_NOT_FOUND": 404,
    "ERR_CHECKLIST_NOT_FOUND": 404,
    "ERR_STANDARD_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PUBLICATION_NOT_FOUND": 404,
    "ERR_COMMENT_NOT_FOUND": 404,
    "ERR_FUND_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    # Not in the PRD section 5 catalogue (which omits a finding-level 404);
    # symmetric extension so GET /gfoa/review-findings/{id} on a missing id
    # reports a 404 instead of a 500.
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_SUBMISSION_STATE_INVALID": 409,
    "ERR_REVIEWER_STATE_INVALID": 409,
    "ERR_REVIEWER_NOT_TRAINED": 409,
    "ERR_REVIEWER_NOT_ELIGIBLE": 409,
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_PUBLICATION_STATE_INVALID": 409,
    "ERR_UNRESOLVED_COMMENTS": 409,
    "ERR_COMMENT_ALREADY_RESOLVED": 409,
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_FINDINGS_INCOMPLETE": 409,
    "ERR_NO_ELIGIBLE_REVIEWER": 409,
    "ERR_CHECKLIST_PIN_STALE": 409,
    "ERR_PINNED_STANDARD_SUPERSEDED": 409,
    "ERR_CHECKLIST_ALREADY_ACTIVE": 409,
    "ERR_DOCUMENT_TYPE_DUPLICATE": 409,
    "ERR_DUPLICATE_SUBMISSION": 409,
    "ERR_AVAILABILITY_WINDOW_OVERLAP": 409,
    "ERR_CYCLE_WINDOW_OVERLAP": 409,
    "ERR_SUBMISSION_WINDOW_CLOSED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_STANDARD_NOT_YET_EFFECTIVE": 409,
    "ERR_STANDARD_STATE_INVALID": 409,
    "ERR_COMMENT_WINDOW_CLOSED": 409,
    "ERR_COMMENT_WINDOW_STILL_OPEN": 409,
    "ERR_REVIEW_QUORUM_FULL": 409,
    "ERR_POOL_EXHAUSTED": 409,
    "ERR_CYCLE_CHECKLIST_MISMATCH": 422,
    "ERR_BUDGET_DOCUMENTS_INCOMPLETE": 422,
    "ERR_PROGRAM_NOT_BUDGET": 422,
    "ERR_UNKNOWN_CRITERION": 422,
    "ERR_CRITERION_SET_INCOMPLETE": 422,
    "ERR_WEIGHT_SUM_INVALID": 422,
    "ERR_GOVERNMENT_NOT_SMALL": 422,
    "ERR_PURPOSE_PROGRAM_MISMATCH": 422,
    "ERR_CHAIR_NOT_ON_COMMITTEE": 422,
    "ERR_STALE_FUND_VERSION": 412,
    "ERR_STALE_PUBLICATION_VERSION": 412,
}


def api_error(error_id, message):
    return ApiError(error_id, ERROR_STATUS[error_id], message)
