"""Error catalog (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # Authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_IDENTITY_NOT_RECOGNIZED": 403,
    "ERR_SITE_SCOPE_VIOLATION": 403,
    "ERR_HAULER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # Existence
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_FOOD_TYPE_NOT_FOUND": 404,
    "ERR_RECIPE_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_ENTRY_NOT_FOUND": 404,
    "ERR_BASELINE_NOT_FOUND": 404,
    "ERR_TARGET_NOT_FOUND": 404,
    "ERR_HAULER_NOT_FOUND": 404,
    "ERR_CONSIGNMENT_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_ALERT_NOT_FOUND": 404,
    "ERR_FINDING_NOT_FOUND": 404,
    "ERR_ROLLUP_NOT_FOUND": 404,
    # Optimistic concurrency
    "ERR_STALE_ENTRY_VERSION": 412,
    "ERR_STALE_SITE_VERSION": 412,
    # State
    "ERR_INVALID_RECIPE_STATE": 409,
    "ERR_INVALID_STATION_STATE": 409,
    "ERR_INVALID_HAULER_STATE": 409,
    "ERR_INVALID_SHIFT_STATE": 409,
    "ERR_INVALID_ENTRY_STATE": 409,
    "ERR_INVALID_BASELINE_STATE": 409,
    "ERR_INVALID_TARGET_STATE": 409,
    "ERR_INVALID_CONSIGNMENT_STATE": 409,
    "ERR_INVALID_TICKET_STATE": 409,
    "ERR_INVALID_ALERT_STATE": 409,
    "ERR_INVALID_FINDING_STATE": 409,
    "ERR_ROLLUP_ALREADY_PUBLISHED": 409,
    "ERR_ENTRY_ROUTED_CANNOT_VOID": 409,
    "ERR_STATION_NOT_ACTIVE": 409,
    "ERR_STATION_CALIBRATION_OVERDUE": 409,
    "ERR_RECIPE_NOT_PUBLISHED": 409,
    "ERR_BASELINE_NOT_CERTIFIED": 409,
    "ERR_HAULER_NOT_APPROVED": 409,
    "ERR_ENTRY_SITE_MISMATCH": 409,
    "ERR_TICKET_HAULER_MISMATCH": 409,
    "ERR_DUPLICATE_SITE_IN_SCOPE": 409,
    "ERR_STATION_OCCUPIED": 409,
    "ERR_BASELINE_WINDOW_OVERLAP": 409,
    "ERR_HAULER_WINDOW_CAPACITY": 409,
    "ERR_ROLLUP_DATA_QUALITY_BLOCKED": 409,
    # Uniqueness
    "ERR_DUPLICATE_SITE_CODE": 409,
    "ERR_DUPLICATE_STATION_CODE": 409,
    "ERR_DUPLICATE_FOOD_TYPE_NAME": 409,
    "ERR_DUPLICATE_RECIPE_CODE": 409,
    "ERR_DUPLICATE_HAULER_NAME": 409,
    "ERR_DUPLICATE_SHIFT": 409,
    "ERR_DUPLICATE_TICKET_NUMBER": 409,
    "ERR_TICKET_ALREADY_SUBMITTED": 409,
    "ERR_ENTRY_ALREADY_CORRECTED": 409,
    # Business rules
    "ERR_CHANNEL_INELIGIBLE_FOOD": 422,
    "ERR_SITE_POSTURE_BLOCKS_DONATION": 422,
    "ERR_HAULER_CHANNEL_UNSUPPORTED": 422,
    "ERR_CAPTURE_IN_FUTURE": 422,
    "ERR_CAPTURE_OUTSIDE_SHIFT_DATE": 422,
    "ERR_DONATION_WINDOW_EXPIRED": 422,
    "ERR_TARGET_WINDOW_BEFORE_BASELINE": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_ALLOCATION_EXCEEDS_UNROUTED": 422,
    "ERR_HAULER_CAPACITY_EXCEEDED": 422,
    "ERR_BASELINE_NO_DATA": 422,
    "ERR_CONSIGNMENT_EMPTY": 422,
    "ERR_LOSS_REASON_STATION_MISMATCH": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_UNAUTHORIZED": "This role is not permitted to perform this operation.",
    "ERR_IDENTITY_NOT_RECOGNIZED": "The supplied identity does not name an existing row.",
    "ERR_SITE_SCOPE_VIOLATION": "The caller may only act on rows of its own site.",
    "ERR_HAULER_SCOPE_VIOLATION": "The caller may only act on rows of its own hauler.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not perform both halves of this duty.",
    "ERR_INVALID_REQUEST": "The request body or query is not valid.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are not valid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
