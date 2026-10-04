"""Error catalog and exception type."""

ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_OFFER_EXPIRED": 422,
    "ERR_VENDOR_DISCRETION": 403,
    "ERR_OTB_FORWARD_EXCEEDED": 422,
    "ERR_OTB_PACKAWAY_EXCEEDED": 422,
    "ERR_TARGET_SEASON_NOT_DRAFT": 422,
    "ERR_HOLD_WINDOW_CLOSED": 422,
    "ERR_TARGET_SEASON_NOT_OPEN": 422,
    "ERR_AGING_REVIEW_PREMATURE": 422,
    "ERR_SEASON_NOT_OPEN": 422,
    "ERR_SEASON_ALREADY_OPEN": 422,
    "ERR_OPEN_LOTS_REMAIN": 422,
    "ERR_PACKAWAY_HOLDS_ACTIVE": 422,
    "ERR_PLAN_NOT_EXECUTABLE": 422,
    "ERR_LOT_ALREADY_ALLOCATED": 422,
    "ERR_CLUSTER_UNCOVERED": 422,
    "ERR_WAREHOUSE_OVER_CAPACITY": 422,
    "ERR_STORE_OVER_CAPACITY": 422,
    "ERR_TICKET_NOT_ISSUED": 422,
    "ERR_TICKET_IN_USE": 422,
    "ERR_RECEIPT_LINE_QTY_INVALID": 422,
    "ERR_NEGATIVE_ON_HAND": 422,
    "ERR_SHRINK_EXCEEDS_ON_HAND": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERRORS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def unauthenticated(msg="missing or invalid X-User-Role / X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", msg)


def unauthorized(msg="role not permitted for the endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg)


def not_found(msg="resource not found"):
    return ApiError("ERR_NOT_FOUND", msg)


def invalid_request(msg="request body is not well-formed"):
    return ApiError("ERR_INVALID_REQUEST", msg)


def invalid_state(msg="resource is not in a valid state for this operation"):
    return ApiError("ERR_INVALID_STATE", msg)
