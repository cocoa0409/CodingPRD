"""Error catalogue -- PRD section 5.  Every id is paired with the HTTP status
the PRD assigns it."""

HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_PERSON_NOT_FOUND": 404,
    "ERR_SHELL_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_MERGE_REQUEST_NOT_FOUND": 404,
    "ERR_CONTENT_ITEM_NOT_FOUND": 404,
    "ERR_ROLLOVER_JOB_NOT_FOUND": 404,
    "ERR_TOOL_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_PASSBACK_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_TERM_CODE": 409,
    "ERR_DUPLICATE_SECTION_CODE": 409,
    "ERR_DUPLICATE_TOOL": 409,
    "ERR_DUPLICATE_PASSBACK": 409,
    "ERR_SHELL_ALREADY_MERGED": 409,
    "ERR_CROSS_TERM_MERGE": 422,
    "ERR_MERGE_CHAIN_FORBIDDEN": 422,
    "ERR_REVIEW_DIMENSION_CONFLICT": 409,
    "ERR_REVIEW_INCOMPLETE": 422,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_FERPA_BLOCK_ACTIVE": 403,
    "ERR_STUDENT_ACCESS_EXPIRED": 403,
    "ERR_TOOL_NOT_APPROVED": 409,
    "ERR_TOOL_VERSION_DRIFT": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_RETENTION_HOLD_ACTIVE": 403,
    "ERR_ADD_DROP_WINDOW_CLOSED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_CONTINUITY_CAP_EXCEEDED": 422,
    "ERR_WINDOW_ALREADY_STARTED": 409,
    "ERR_SANDBOX_EXPIRED": 409,
    "ERR_PURGE_NOT_DUE": 409,
    "ERR_TERM_POSTURE_FROZEN": 409,
    "ERR_SHELL_NOT_PUBLISH_READY": 422,
    "ERR_SHELL_STATE_BLOCKS_ENROLLMENT": 409,
    "ERR_SANDBOX_NOT_PUBLISHABLE": 422,
    "ERR_ROLLOVER_SOURCE_INELIGIBLE": 422,
    "ERR_ROLLOVER_TARGET_NOT_EMPTY": 422,
    "ERR_ROLE_CONFLICT": 409,
    "ERR_SYNC_EPOCH_OUT_OF_ORDER": 409,
    "ERR_NO_GRADES_STAGED": 422,
    "ERR_OPEN_DISPUTES_BLOCK_CLOSE": 422,
    "ERR_ROLLOVER_INCOMPLETE": 422,
    "ERR_ITEM_HAS_SUBMISSIONS": 409,
    "ERR_SANDBOX_QUOTA_EXCEEDED": 422,
    "ERR_SEAT_CAP_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role must be present and non-empty.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the referenced resource.",
    "ERR_INVALID_REQUEST": "The request payload is not well formed.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not permitted from the current state.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def require(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)
