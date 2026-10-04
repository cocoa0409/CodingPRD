"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error ID constants (scaffold §errors)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_OFFICE_POSTURE_BLOCKED = "ERR_OFFICE_POSTURE_BLOCKED"
ERR_POA_EXPIRED = "ERR_POA_EXPIRED"
ERR_POA_NOT_DRAFT = "ERR_POA_NOT_DRAFT"
ERR_NOTICE_NOT_TERMINAL = "ERR_NOTICE_NOT_TERMINAL"
ERR_CLAIM_ALREADY_RESOLVED = "ERR_CLAIM_ALREADY_RESOLVED"
ERR_PROTECTION_REQUIRED = "ERR_PROTECTION_REQUIRED"
ERR_DUPLICATE_PRODUCT = "ERR_DUPLICATE_PRODUCT"
ERR_PRODUCT_INELIGIBLE = "ERR_PRODUCT_INELIGIBLE"
ERR_AGENT_CAPACITY = "ERR_AGENT_CAPACITY"
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"
ERR_INVALID_WINDOW = "ERR_INVALID_WINDOW"
ERR_CLOSE_PERIOD_REGRESSION = "ERR_CLOSE_PERIOD_REGRESSION"
ERR_INVALID_COMPONENTS = "ERR_INVALID_COMPONENTS"
ERR_AMEND_REQUIRES_ORIGINAL = "ERR_AMEND_REQUIRES_ORIGINAL"
ERR_DUPLICATE_ESCROW = "ERR_DUPLICATE_ESCROW"
ERR_REMEDIATION_OVERDUE = "ERR_REMEDIATION_OVERDUE"
ERR_DUPLICATE_CLIENT_EMAIL = "ERR_DUPLICATE_CLIENT_EMAIL"
ERR_DOWNGRADE_FORBIDDEN = "ERR_DOWNGRADE_FORBIDDEN"
ERR_VOID_CLAIMS_OPEN = "ERR_VOID_CLAIMS_OPEN"


def unauthenticated(msg="Missing or invalid X-User-Role or X-User-ID headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def validation(msg="Malformed input"):
    return ApiError(ERR_VALIDATION, msg, 400)


def invalid_state(msg="Target resource not in a state from which the requested transition is defined"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def already_terminal(msg="Target resource is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, msg, 409)


def stale_version(msg="Expected version does not match the current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)
