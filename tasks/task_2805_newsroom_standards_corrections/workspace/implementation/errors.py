"""Error catalog (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_HEIGHTENED_REQUIRES_EXEC": 403,
    # existence
    "ERR_NEWSROOM_NOT_FOUND": 404,
    "ERR_JOURNALIST_NOT_FOUND": 404,
    "ERR_REVIEWER_NOT_FOUND": 404,
    "ERR_STORY_NOT_FOUND": 404,
    "ERR_SOURCE_APPROVAL_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_CORRECTION_REQUEST_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    "ERR_ACTIVITY_REQUEST_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_INTERVAL": 400,
    # optimistic concurrency
    "ERR_STALE_STORY_VERSION": 412,
    "ERR_STALE_REVIEWER_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_STORY_NOT_CLEARED": 409,
    "ERR_STORY_NOT_PUBLISHED": 409,
    "ERR_REVIEW_ROUND_NOT_OPEN": 409,
    "ERR_LEGAL_VERDICT_REQUIRED": 409,
    "ERR_SOURCE_ALREADY_DECIDED": 409,
    "ERR_CORRECTION_NOT_INVESTIGATED": 409,
    "ERR_APPEAL_NOT_ALLOWED": 409,
    "ERR_POSTURE_LOCKDOWN": 409,
    "ERR_JOURNALIST_SUSPENDED": 409,
    "ERR_OUTSIDE_ACTIVITY_OVERLAP": 409,
    "ERR_REVIEWER_SLOT_CONFLICT": 409,
    "ERR_DUPLICATE_TRAINING_MODULE": 409,
    "ERR_DUPLICATE_SOURCE_ALIAS": 409,
    # business rules
    "ERR_INSUFFICIENT_SOURCE_DOCUMENTATION": 422,
    "ERR_INSUFFICIENT_CORROBORATION": 422,
    "ERR_TRAINING_NOT_CURRENT": 422,
    "ERR_SOURCE_NOT_APPROVED": 422,
    "ERR_CROSS_NEWSROOM_REFERENCE": 422,
    "ERR_REVIEWER_DISCIPLINE_MISMATCH": 422,
    "ERR_COI_DISCLOSURE_PENDING": 422,
    "ERR_ACTIVITY_BEAT_RESTRICTED": 422,
    "ERR_UNPUBLISH_NOT_JUSTIFIED": 422,
    "ERR_NOTICE_TEXT_REQUIRED": 422,
    "ERR_REVIEWER_CAPACITY_EXCEEDED": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognized authentication headers.",
    "ERR_UNAUTHORIZED": "The acting identity is not permitted to perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user is a party to the matter being judged.",
    "ERR_HEIGHTENED_REQUIRES_EXEC": "Only an ExecutiveEditor may clear a review under HEIGHTENED posture.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_INTERVAL": "The supplied interval or instant is invalid.",
    "ERR_INVALID_STATE": "The requested transition is not available from the current state.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        if message is None:
            message = DEFAULT_MESSAGE.get(
                error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
            )
        self.message = message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
