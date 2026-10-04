"""Validation exception carrying error_id + http_status."""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SELF_ACCEPT_FORBIDDEN = "ERR_SELF_ACCEPT_FORBIDDEN"
ERR_PROCUREMENT_GATE = "ERR_PROCUREMENT_GATE"
ERR_AUDIT_OVERLAP = "ERR_AUDIT_OVERLAP"
ERR_HEARING_IN_PAST = "ERR_HEARING_IN_PAST"
ERR_HEARING_WINDOW = "ERR_HEARING_WINDOW"
ERR_OUT_OF_ORDER_RESULT = "ERR_OUT_OF_ORDER_RESULT"
ERR_SAR_SECTION_UNKNOWN = "ERR_SAR_SECTION_UNKNOWN"
ERR_CAPACITY_EXCEEDED = "ERR_CAPACITY_EXCEEDED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_ESCALATION_OUT_OF_RANGE = "ERR_ESCALATION_OUT_OF_RANGE"
ERR_DUPLICATE = "ERR_DUPLICATE"
ERR_DCA_NOT_CERTIFIED = "ERR_DCA_NOT_CERTIFIED"
ERR_VALIDATION = "ERR_VALIDATION"


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="missing or invalid X-User-Role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def err_unauthorized(msg="role lacks permission"):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def err_not_found(msg="resource not found"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_invalid_state(msg="invalid state for transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_validation(msg="invalid payload"):
    return ApiError(ERR_VALIDATION, 400, msg)
