"""Error classes and HTTP plumbing."""

ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VALIDATION": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_PROGRAM_HAS_ACTIVE_STORES": 409,
    "ERR_PROGRAM_CLOSE_BLOCKED": 409,
    "ERR_TRADE_AREA_NOT_QUALIFIED": 409,
    "ERR_NO_FEASIBLE_FORMAT": 422,
    "ERR_STORE_PRECONDITION": 409,
    "ERR_SITE_CONTROL_ACTIVE": 409,
    "ERR_DUPLICATE_ACTIVE": 409,
    "ERR_DEVELOPER_CAPACITY_EXCEEDED": 409,
    "ERR_DC_CAPACITY_EXCEEDED": 409,
    "ERR_FIXTURE_LEAD_TIME": 409,
    "ERR_OPENING_TOO_EARLY": 409,
    "ERR_CANNIBALIZATION_BLOCKED": 409,
    "ERR_STUDY_NOT_FINAL": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CAPITAL_BUDGET_EXCEEDED": 409,
    "ERR_BAD_REFERENCE": 422,
    "ERR_NO_ACTIVE_ASSIGNMENT": 409,
    "ERR_OPENING_PLAN_STATE": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else ERRORS[error_id]


def err_unauthenticated(msg="X-User-Role header missing or not a declared role"):
    return ApiError("ERR_UNAUTHENTICATED", msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg)


def err_invalid_request(msg="Missing or ill-typed required field"):
    return ApiError("ERR_INVALID_REQUEST", msg)


def err_validation(msg="Field value violates a declared constraint"):
    return ApiError("ERR_VALIDATION", msg)
