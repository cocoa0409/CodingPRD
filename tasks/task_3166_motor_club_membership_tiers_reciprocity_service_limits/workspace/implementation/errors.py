"""Error types and error id constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error id constants (exactly as in the scaffold error catalog)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_WAITING_PERIOD_ACTIVE = "ERR_WAITING_PERIOD_ACTIVE"
ERR_SOD_CONFLICT = "ERR_SOD_CONFLICT"
ERR_MEMBERSHIP_NOT_SERVICEABLE = "ERR_MEMBERSHIP_NOT_SERVICEABLE"
ERR_MEMBER_NOT_COVERED = "ERR_MEMBER_NOT_COVERED"
ERR_TERRITORY_NOT_FOUND = "ERR_TERRITORY_NOT_FOUND"
ERR_REINSTATEMENT_WINDOW_EXPIRED = "ERR_REINSTATEMENT_WINDOW_EXPIRED"
ERR_REFUND_WINDOW_EXPIRED = "ERR_REFUND_WINDOW_EXPIRED"
ERR_PERIOD_NOT_CLOSABLE = "ERR_PERIOD_NOT_CLOSABLE"
ERR_OPEN_SERVICE_CALLS = "ERR_OPEN_SERVICE_CALLS"
ERR_DISPATCH_BEYOND_CANCEL = "ERR_DISPATCH_BEYOND_CANCEL"
ERR_TIER_MOVE_INVALID = "ERR_TIER_MOVE_INVALID"
ERR_HOUSEHOLD_LIMIT = "ERR_HOUSEHOLD_LIMIT"
ERR_INSUFFICIENT_TRUCK_STOCK = "ERR_INSUFFICIENT_TRUCK_STOCK"
ERR_PRODUCT_TIER_GATE = "ERR_PRODUCT_TIER_GATE"
ERR_LINE_ALREADY_SWEPT = "ERR_LINE_ALREADY_SWEPT"
ERR_CLUB_SUSPENDED = "ERR_CLUB_SUSPENDED"
ERR_PROVIDER_BUSY = "ERR_PROVIDER_BUSY"


def unauthenticated(msg="Missing or invalid X-User-ID / X-User-Role headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Malformed request payload"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Operation not permitted in the current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def business(error_id, msg):
    return ApiError(error_id, 422, msg)
