"""Error catalogue for the consumption-credit warehouse governance API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status=400):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_INVALID": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_ACCOUNT_DRAINING": 422,
    "ERR_ROLE_CONFLICT": 422,
    "ERR_CONTRACT_CREDIT_EXHAUSTED": 422,
    "ERR_SHARE_SELF_CONSUMPTION": 422,
    "ERR_SHARE_NOT_PUBLISHED": 422,
    "ERR_TERM_OVERLAP": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_WAREHOUSE_SUSPENDED": 409,
    "ERR_AUTO_SUSPEND_RANGE": 400,
    "ERR_SESSION_NOT_OPEN": 409,
    "ERR_CLUSTER_RANGE": 400,
    "ERR_STORAGE_DAYS_RANGE": 400,
    "ERR_MONITOR_MISSING": 422,
    "ERR_QUOTA_EXCEEDED": 422,
    "ERR_LISTING_NOT_PUBLISHED": 409,
    "ERR_FREE_LISTING_NOT_PAYABLE": 422,
    "ERR_REPLICATION_REGION_INVALID": 422,
    "ERR_REPLICATION_SIZE_RANGE": 400,
    "ERR_DISPUTE_SELF_RESOLVE": 422,
    "ERR_DRAWDOWN_AMOUNT_RANGE": 400,
}


def err(error_id, message):
    return ApiError(error_id, message, ERR_STATUS[error_id])
