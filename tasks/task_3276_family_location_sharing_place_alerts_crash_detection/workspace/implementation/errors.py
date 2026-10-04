"""Error types and error-id constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_CIRCLE_FROZEN = "ERR_CIRCLE_FROZEN"
ERR_CIRCLE_RESTRICTED = "ERR_CIRCLE_RESTRICTED"
ERR_WELLNESS_EXPIRED = "ERR_WELLNESS_EXPIRED"
ERR_DISPATCH_ALREADY_STAGED = "ERR_DISPATCH_ALREADY_STAGED"
ERR_TRIP_NOT_OPEN = "ERR_TRIP_NOT_OPEN"
ERR_CONSENT_NOT_GRANTED = "ERR_CONSENT_NOT_GRANTED"
ERR_MINOR_CONSENT_LOCKED = "ERR_MINOR_CONSENT_LOCKED"
ERR_PRIVACY_SELF_ONLY = "ERR_PRIVACY_SELF_ONLY"
ERR_PLACE_CONFIG_INVALID = "ERR_PLACE_CONFIG_INVALID"
ERR_FIX_CLOCK_SKEW = "ERR_FIX_CLOCK_SKEW"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_ROLE_INCOMPATIBLE = "ERR_ROLE_INCOMPATIBLE"
ERR_PLACE_OVERLAP = "ERR_PLACE_OVERLAP"
ERR_ASSISTANCE_UNITS_EXHAUSTED = "ERR_ASSISTANCE_UNITS_EXHAUSTED"
ERR_NO_IDENTITY_CREDIT = "ERR_NO_IDENTITY_CREDIT"
ERR_CRASH_BELOW_THRESHOLD = "ERR_CRASH_BELOW_THRESHOLD"
ERR_STALE_VERSION = "ERR_STALE_VERSION"


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def err_forbidden(msg="Role not permitted for this operation"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_invalid_state(msg="Requested transition not allowed from current state"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_invalid_request(msg="Malformed request"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)
