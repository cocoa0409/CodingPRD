"""Error identifiers and the API exception type.

Error ids and their HTTP status codes come from SCAFFOLD.yaml section 1.6
(the error catalog) and PRD section 5.
"""


class ApiError(Exception):
    """An error that maps directly onto the standard error envelope."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)


HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_DC_NOT_FOUND": 404,
    "ERR_LINE_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_DC_LOCKDOWN": 409,
    "ERR_ITEM_SUSPENDED": 409,
    "ERR_NO_ELIGIBLE_DC": 409,
    "ERR_DC_NOT_CANDIDATE": 409,
    "ERR_INBOUND_CAPACITY_EXCEEDED": 409,
    "ERR_CURATION_NOT_APPROVED": 409,
    "ERR_CURATION_ATTRIBUTES_MISSING": 409,
    "ERR_CUTOFF_WINDOW_PASSED": 422,
    "ERR_PROMISE_DATE_IN_PAST": 422,
    "ERR_RETURN_PART_NUMBER_REQUIRED": 422,
    "ERR_SUPPLIER_CANDIDATE_EMPTY": 409,
    "ERR_INVALID_REQUEST": 400,
}

# Convenience constructors -------------------------------------------------


def invalid_request(message):
    return ApiError("ERR_INVALID_REQUEST", message, 400)


def unauthenticated(message="Missing or invalid X-User-ID / X-User-Role headers."):
    return ApiError("ERR_UNAUTHENTICATED", message, 401)


def unauthorized(message="The calling role may not invoke this operation."):
    return ApiError("ERR_UNAUTHORIZED", message, 403)


def not_found(error_id, message):
    return ApiError(error_id, message, 404)