"""Error catalogue and the ApiError exception."""

ERROR_HTTP = {
    # authentication, authorization, request shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_CONFLICT": 403,
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CLUB_NOT_FOUND": 404,
    "ERR_SHOW_NOT_FOUND": 404,
    "ERR_JUDGE_NOT_FOUND": 404,
    "ERR_SLOT_NOT_FOUND": 404,
    "ERR_CLASS_NOT_FOUND": 404,
    "ERR_HANDLER_NOT_FOUND": 404,
    "ERR_DOG_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_RING_BLOCK_NOT_FOUND": 404,
    "ERR_PROTEST_NOT_FOUND": 404,
    "ERR_FILING_NOT_FOUND": 404,
    # lifecycle state
    "ERR_SHOW_NOT_IN_DRAFT": 409,
    "ERR_SHOW_NOT_ACCEPTING_ENTRIES": 409,
    "ERR_SLOT_NOT_CONFIRMED": 409,
    "ERR_CLASS_NOT_OPEN": 409,
    "ERR_CLASS_NOT_READY": 409,
    "ERR_CLASSES_NOT_COMPLETE": 409,
    "ERR_PROTEST_NOT_IN_REVIEW": 409,
    "ERR_INVALID_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_SHOW_VERSION": 412,
    "ERR_STALE_JUDGE_VERSION": 412,
    # welfare and eligibility
    "ERR_HEAT_RESTRICTION_ACTIVE": 409,
    "ERR_BITCH_IN_SEASON": 409,
    "ERR_HANDLER_SUSPENDED": 403,
    "ERR_DOG_UNDER_MINIMUM_AGE": 409,
    "ERR_CLUB_NOT_ACTIVE": 409,
    "ERR_JUDGE_NOT_ACTIVE": 409,
    "ERR_JUDGE_NOT_APPROVED_FOR_GROUP": 409,
    "ERR_JUDGE_NOT_APPROVED_FOR_DISCIPLINE": 409,
    "ERR_PANEL_ROLE_MISMATCH": 409,
    "ERR_PARENT_CLASS_LEVEL_INVALID": 409,
    "ERR_BREED_MISMATCH": 409,
    "ERR_MEASUREMENT_REQUIRED": 409,
    "ERR_JUMP_HEIGHT_MISMATCH": 409,
    "ERR_MEASUREMENT_LOCKED": 409,
    "ERR_COURSE_DESIGN_INVALID": 409,
    # windows, geometry, capacity
    "ERR_ENTRY_WINDOW_CLOSED": 409,
    "ERR_RING_BLOCK_OVERLAP": 409,
    "ERR_JUDGE_REST_BUFFER_VIOLATION": 409,
    "ERR_PROTEST_WINDOW_EXPIRED": 409,
    "ERR_DUPLICATE_ENTRY": 409,
    "ERR_CLASS_ENTRY_LIMIT_REACHED": 409,
    "ERR_SHOW_ENTRY_CAP_REACHED": 409,
    "ERR_JUDGE_ASSIGNMENT_LIMIT": 409,
    "ERR_JUDGE_DOG_LIMIT_EXCEEDED": 409,
    "ERR_PLACEMENT_SET_INVALID": 409,
    "ERR_FILING_ALREADY_OPEN": 409,
    "ERR_OPEN_PROTEST_BLOCKS_FILING": 409,
    "ERR_CLUB_ALLOWANCE_EXHAUSTED": 409,
    "ERR_PROTEST_DEPOSIT_INSUFFICIENT": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The caller role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the target resource.",
    "ERR_SEGREGATION_CONFLICT": "Segregation of duties forbids this action.",
    "ERR_INVALID_REQUEST": "The request is not well formed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 409)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
