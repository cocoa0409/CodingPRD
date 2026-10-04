"""Error IDs and HTTP status mapping (PRD section 5)."""
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_WINDOW_EXPIRED = "ERR_WINDOW_EXPIRED"
    ERR_DUPLICATE_PENDING = "ERR_DUPLICATE_PENDING"
    ERR_ROFR_NOT_ENABLED = "ERR_ROFR_NOT_ENABLED"
    ERR_INVALID_AMOUNT = "ERR_INVALID_AMOUNT"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_WINDOW_EXPIRED: 422,
    ApiErrorId.ERR_DUPLICATE_PENDING: 409,
    ApiErrorId.ERR_ROFR_NOT_ENABLED: 422,
    ApiErrorId.ERR_INVALID_AMOUNT: 422,
}

# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
