"""Error IDs and HTTP status mapping (PRD error catalogue).

The mapping is registered with the framework at import time so that
validate_error() auto-checks the HTTP status for every known error_id.
"""
from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
    ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
    ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
    ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
    ERR_MATCH_BINDING = "ERR_MATCH_BINDING"                # 409
    ERR_MATCH_ALREADY_RUN = "ERR_MATCH_ALREADY_RUN"        # 409
    ERR_CYCLE_BLOCKED = "ERR_CYCLE_BLOCKED"                # 409
    ERR_WRONG_CYCLE_PHASE = "ERR_WRONG_CYCLE_PHASE"        # 409
    ERR_WINDOW_CLOSED = "ERR_WINDOW_CLOSED"                # 409
    ERR_CYCLE_OVERLAP = "ERR_CYCLE_OVERLAP"                # 409
    ERR_PROGRAM_OVERLAP = "ERR_PROGRAM_OVERLAP"            # 409
    ERR_REFERRAL_NOT_FOUND = "ERR_REFERRAL_NOT_FOUND"      # 422
    ERR_UNKNOWN_COLLEGE = "ERR_UNKNOWN_COLLEGE"            # 422
    ERR_COLLEGE_INACTIVE = "ERR_COLLEGE_INACTIVE"          # 409
    ERR_DUPLICATE_APPLICATION = "ERR_DUPLICATE_APPLICATION"  # 409
    ERR_EMAIL_TAKEN = "ERR_EMAIL_TAKEN"                    # 409
    ERR_RANK_ORDER_INVALID = "ERR_RANK_ORDER_INVALID"      # 422
    ERR_TOO_MANY_RANKS = "ERR_TOO_MANY_RANKS"              # 422
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"  # 403
    ERR_ACADEMIC_INELIGIBLE = "ERR_ACADEMIC_INELIGIBLE"    # 422
    ERR_INCOME_INELIGIBLE = "ERR_INCOME_INELIGIBLE"        # 422
    ERR_VERIFICATION_REQUIRED = "ERR_VERIFICATION_REQUIRED"  # 409


HTTP_STATUS_CODES = {
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_UNAUTHORIZED: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_MATCH_BINDING: 409,
    ApiErrorId.ERR_MATCH_ALREADY_RUN: 409,
    ApiErrorId.ERR_CYCLE_BLOCKED: 409,
    ApiErrorId.ERR_WRONG_CYCLE_PHASE: 409,
    ApiErrorId.ERR_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_CYCLE_OVERLAP: 409,
    ApiErrorId.ERR_PROGRAM_OVERLAP: 409,
    ApiErrorId.ERR_REFERRAL_NOT_FOUND: 422,
    ApiErrorId.ERR_UNKNOWN_COLLEGE: 422,
    ApiErrorId.ERR_COLLEGE_INACTIVE: 409,
    ApiErrorId.ERR_DUPLICATE_APPLICATION: 409,
    ApiErrorId.ERR_EMAIL_TAKEN: 409,
    ApiErrorId.ERR_RANK_ORDER_INVALID: 422,
    ApiErrorId.ERR_TOO_MANY_RANKS: 422,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_ACADEMIC_INELIGIBLE: 422,
    ApiErrorId.ERR_INCOME_INELIGIBLE: 422,
    ApiErrorId.ERR_VERIFICATION_REQUIRED: 409,
}

# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
