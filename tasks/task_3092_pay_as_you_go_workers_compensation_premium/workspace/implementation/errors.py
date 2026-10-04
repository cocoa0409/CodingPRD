"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_MONOPOLISTIC_STATE_EXCLUDED = "ERR_MONOPOLISTIC_STATE_EXCLUDED"
ERR_CLASS_CODE_NOT_ON_POLICY = "ERR_CLASS_CODE_NOT_ON_POLICY"
ERR_PAYROLL_PERIOD_OVERLAP = "ERR_PAYROLL_PERIOD_OVERLAP"
ERR_RATING_TABLE_OVERLAP = "ERR_RATING_TABLE_OVERLAP"
ERR_RETRO_WINDOW_INVALID = "ERR_RETRO_WINDOW_INVALID"
ERR_BILLING_SUSPENDED = "ERR_BILLING_SUSPENDED"
ERR_IDEMPOTENCY_CONFLICT = "ERR_IDEMPOTENCY_CONFLICT"
ERR_PAYMENT_AMOUNT_MISMATCH = "ERR_PAYMENT_AMOUNT_MISMATCH"
ERR_TAX_FILING_MISSING = "ERR_TAX_FILING_MISSING"
ERR_DUPLICATE_INVOICE = "ERR_DUPLICATE_INVOICE"
ERR_POLICY_NOT_ACTIVE = "ERR_POLICY_NOT_ACTIVE"


def unauthenticated(msg="Missing or malformed auth headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def forbidden(msg="Role not permitted for endpoint"):
    return ApiError(ERR_FORBIDDEN, msg, 403)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg="Malformed request body"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg="Transition not declared from current state"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg="expected_policy_version does not match current Policy version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)
