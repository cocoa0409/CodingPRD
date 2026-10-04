"""Error types and the error catalog (IDs + HTTP statuses)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error catalog — id -> http status
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PAGE_NOT_ACTIVE": 409,
    "ERR_USER_NOT_ACTIVE": 409,
    "ERR_SOLICITATION_SUSPECT": 422,
    "ERR_REVIEW_EVIDENCE_LOCKED": 409,
    "ERR_EDIT_WINDOW_EXPIRED": 410,
    "ERR_CLAIM_CONFLICT": 409,
    "ERR_VERIFICATION_EXPIRED": 410,
    "ERR_AD_ACCOUNT_CONFLICT": 409,
    "ERR_CAMPAIGN_CONFIG": 422,
    "ERR_CAMPAIGN_OUT_OF_WINDOW": 409,
    "ERR_CAMPAIGN_NOT_CALL_TRACKING": 422,
    "ERR_BUDGET_EXCEEDED": 422,
    "ERR_IDEMPOTENCY_CONFLICT": 409,
    "ERR_ATTRIBUTION_WINDOW": 422,
    "ERR_COMPLAINT_CONFLICT": 409,
    "ERR_REVIEW_STATE_CHANGED": 409,
    "ERR_SELF_ACTION": 403,
    "ERR_CASE_TARGETS_INVALID": 422,
    "ERR_ALERT_CONFLICT": 409,
    "ERR_ALERT_CASE_ACTIVE": 409,
    "ERR_MEDIA_REQUEST_REFUSED": 422,
    "ERR_NOTICE_PERIOD_ACTIVE": 409,
    "ERR_MERGE_CONFLICT": 409,
}


def err(error_id, message):
    return ApiError(error_id, ERRORS[error_id], message)


def not_found(msg="resource not found"):
    return err("ERR_NOT_FOUND", msg)


def invalid_request(msg="malformed payload"):
    return err("ERR_INVALID_REQUEST", msg)


def invalid_state(msg="operation not permitted in current state"):
    return err("ERR_INVALID_STATE", msg)


def forbidden(msg="role not permitted for this endpoint"):
    return err("ERR_FORBIDDEN", msg)
