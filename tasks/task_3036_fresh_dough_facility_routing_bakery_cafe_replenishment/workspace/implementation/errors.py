"""Error catalogue and the ApiError exception used across the service."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else STATUS.get(error_id, 400)
        self.message = message if message else DEFAULT_MESSAGE.get(error_id, error_id)
        super(ApiError, self).__init__(self.message)


# error_id -> HTTP status (PRD section 5 error catalogue)
STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_LOCKED": 409,
    "ERR_PLAN_LOCKED": 409,
    "ERR_ORDER_CUTOFF_PASSED": 409,
    "ERR_SUBSTITUTION_FORBIDDEN": 422,
    "ERR_SHELF_LIFE_EXCEEDED": 422,
    "ERR_STOP_WINDOW_VIOLATION": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_DUPLICATE": 409,
    "ERR_TOO_EARLY": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_VALIDATION": 400,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or unrecognized.",
    "ERR_FORBIDDEN_ROLE": "The caller's role may not perform this operation.",
    "ERR_NOT_FOUND": "Resource not found.",
    "ERR_INVALID_STATE": "The resource's current state does not permit this transition.",
    "ERR_ORDER_LOCKED": "The order is LOCKED or later; amend/cancel is no longer allowed.",
    "ERR_PLAN_LOCKED": "The production plan is LOCKED or later; new orders cannot attach.",
    "ERR_ORDER_CUTOFF_PASSED": "The order cutoff for this dough type and date has passed.",
    "ERR_SUBSTITUTION_FORBIDDEN": "A short shipment on a no-substitution dough type cannot be filled by another dough type.",
    "ERR_SHELF_LIFE_EXCEEDED": "The dough has expired; baking may no longer start.",
    "ERR_STOP_WINDOW_VIOLATION": "The arrival falls outside the cafe's delivery window, or windows on one cafe overlap.",
    "ERR_CREDIT_LIMIT_EXCEEDED": "The cafe's credit limit would be exceeded.",
    "ERR_CAPACITY_EXCEEDED": "The plan or route would exceed its capacity ceiling.",
    "ERR_DUPLICATE": "A uniqueness constraint was violated.",
    "ERR_TOO_EARLY": "The operation was attempted before its scheduled instant.",
    "ERR_STALE_VERSION": "The supplied optimistic-concurrency token is stale.",
    "ERR_VALIDATION": "The request body carries a malformed or out-of-range field.",
    "ERR_METHOD_NOT_ALLOWED": "Method not allowed for this resource.",
    "ERR_INTERNAL": "Internal server error.",
}
