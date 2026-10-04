"""Error types and the full error catalog (id -> http status)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_NOT_LISTING_OWNER": 403,
    "ERR_NOT_EDIT_AUTHOR": 403,
    "ERR_NOT_TICKET_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_LISTING_ALREADY_CLAIMED": 409,
    "ERR_LISTING_SUSPENDED": 409,
    "ERR_LISTING_NOT_VERIFIABLE": 409,
    "ERR_ATTEMPT_EXPIRED": 409,
    "ERR_ATTEMPTS_EXHAUSTED": 409,
    "ERR_VERIFICATION_COOLDOWN": 409,
    "ERR_TOO_MANY_ATTEMPTS": 409,
    "ERR_KEYWORD_STUFFING": 422,
    "ERR_PROHIBITED_CATEGORY": 422,
    "ERR_GEO_OUT_OF_REGION": 422,
    "ERR_STRIKES_BELOW_THRESHOLD": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_EDIT_ALREADY_ASSIGNED": 409,
    "ERR_DUPLICATE_SUBMISSION": 409,
    "ERR_FLAG_LIMIT_REACHED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_IMAGERY_CAPACITY": 409,
    "ERR_OUTSIDE_WINDOW": 409,
    "ERR_BLUR_INCOMPLETE": 422,
    "ERR_REGION_FROZEN": 409,
    "ERR_ROUTING_WINDOW_CONFLICT": 409,
    "ERR_CONTRIBUTOR_RESTRICTED": 403,
}


def raise_err(error_id, message=None):
    raise ApiError(error_id, message or error_id, ERR[error_id])
