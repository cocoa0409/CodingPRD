"""Error catalog: ApiError exception carrying error_id/message/http_status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def validation(msg="Malformed input"):
    return ApiError("ERR_VALIDATION", msg, 400)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def stale_version(msg="Stale expected_agreement_version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def invalid_state(msg="Invalid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def duty_segregation(msg="Decider must differ from the verifying administrator"):
    return ApiError("ERR_DUTY_SEGREGATION", msg, 409)


def window_expired(msg="Time window has expired"):
    return ApiError("ERR_WINDOW_EXPIRED", msg, 409)


def capacity_exceeded(msg="Capacity limit reached"):
    return ApiError("ERR_CAPACITY_EXCEEDED", msg, 409)


def window_overlap(msg="Time window overlap"):
    return ApiError("ERR_WINDOW_OVERLAP", msg, 409)


def loaner_pool_empty(msg="No available loaner unit of the required tool model"):
    return ApiError("ERR_LOANER_POOL_EMPTY", msg, 409)


def open_claims(msg="Agreement has open theft claims"):
    return ApiError("ERR_AGREEMENT_HAS_OPEN_CLAIMS", msg, 409)


def return_incomplete(msg="Not all assets returned or retired"):
    return ApiError("ERR_RETURN_INCOMPLETE", msg, 409)


def application_approval_required(msg="Line requires a DOCUMENTED ANCHOR_DESIGN support case"):
    return ApiError("ERR_APPLICATION_APPROVAL_REQUIRED", msg, 422)


def credit_limit_exceeded(msg="Credit limit exceeded"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", msg, 402)


def duplicate(msg="Unique constraint violation"):
    return ApiError("ERR_DUPLICATE", msg, 409)
