"""Error catalogue (PRD section 5) and the API exception type."""

ERROR_HTTP = {
    # auth / identity
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_STAFF_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_FEED_NOT_FOUND": 404,
    "ERR_HANDOFF_NOT_FOUND": 404,
    "ERR_SAFETY_EVENT_NOT_FOUND": 404,
    "ERR_REASSESSMENT_NOT_FOUND": 404,
    "ERR_COST_ENTRY_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_ORDER_VERSION": 412,
    # state
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_STATION_STATE": 409,
    "ERR_INVALID_FEED_STATE": 409,
    "ERR_INVALID_EVENT_STATE": 409,
    "ERR_INVALID_HANDOFF_STATE": 409,
    "ERR_PATIENT_DISCHARGED": 409,
    "ERR_STAFF_NOT_AVAILABLE": 409,
    "ERR_RECENT_SAFETY_EVENT_BLOCKS_DISCONTINUATION": 409,
    # business: safety / competency
    "ERR_DEESCALATION_CERT_EXPIRED": 422,
    "ERR_COMPETENCY_INSUFFICIENT": 422,
    "ERR_STAFF_SUSPENDED": 422,
    "ERR_VOLUNTEER_NOT_ELIGIBLE": 422,
    "ERR_VIDEO_MODALITY_NOT_PERMITTED": 422,
    # business: temporal
    "ERR_STAFF_SHIFT_OVERLAP": 409,
    "ERR_STAFF_REST_BUFFER_VIOLATION": 409,
    "ERR_INVALID_SHIFT_WINDOW": 422,
    "ERR_OUTSIDE_SHIFT_WINDOW": 422,
    "ERR_BREAK_NOT_YET_ELIGIBLE": 422,
    "ERR_BREAK_TOO_SHORT": 422,
    # business: capacity / uniqueness
    "ERR_SPAN_OF_CONTROL_EXCEEDED": 409,
    "ERR_STATION_HAS_ACTIVE_FEEDS": 409,
    "ERR_DUPLICATE_ACTIVE_FEED": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    # business: referential / documentation
    "ERR_FLOAT_AUTHORIZATION_MISSING": 422,
    "ERR_HANDOFF_ORDER_MISMATCH": 422,
    "ERR_HANDOFF_NOT_SIGNED": 422,
    "ERR_REVIEW_FINDINGS_REQUIRED": 422,
    "ERR_REASSESSMENT_REQUIRED_BEFORE_REVIEW": 422,
    # business: fiscal
    "ERR_UNIT_BUDGET_EXCEEDED": 402,
    "ERR_UNIT_RESTRICTED_AGENCY_BLOCKED": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are both required and must be non-empty.",
    "ERR_ROLE_NOT_PERMITTED": "The supplied X-User-Role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting user does not own the resource this operation targets.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties requires a second, distinct acting user.",
    "ERR_INVALID_REQUEST": "The request body or query string failed shape validation.",
    "ERR_STALE_ORDER_VERSION": "expected_order_version does not match the observation order's current version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
