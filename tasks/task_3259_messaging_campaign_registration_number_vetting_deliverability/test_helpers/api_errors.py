"""Error identifiers and their HTTP statuses, transcribed from PRD section 5.

The map is registered with the shared validator layer at import time so
that ``validate_error(response, ERR_X)`` can check the HTTP status without
every call site restating it.
"""

from prd_bench_local_runner.testing.validators import set_error_http_status_map

# ─── Authentication, authorization, existence ─────────────────────────────

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"

# ─── Field shape and rejection reasons ────────────────────────────────────

ERR_VALIDATION = "ERR_VALIDATION"
ERR_REJECTION_REASON_INVALID = "ERR_REJECTION_REASON_INVALID"

# ─── Account gates ────────────────────────────────────────────────────────

ERR_ACCOUNT_SUSPENDED = "ERR_ACCOUNT_SUSPENDED"
ERR_ACCOUNT_CLOSED = "ERR_ACCOUNT_CLOSED"

# ─── State and concurrency ────────────────────────────────────────────────

ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"

# ─── Brand gates ──────────────────────────────────────────────────────────

ERR_BRAND_SCORE_TOO_LOW = "ERR_BRAND_SCORE_TOO_LOW"
ERR_BRAND_NOT_VERIFIED = "ERR_BRAND_NOT_VERIFIED"
ERR_BRAND_REVOKED = "ERR_BRAND_REVOKED"

# ─── Campaign path gates ──────────────────────────────────────────────────

ERR_TOLLFREE_VETTING_INSUFFICIENT = "ERR_TOLLFREE_VETTING_INSUFFICIENT"
ERR_SHORT_CODE_GEO = "ERR_SHORT_CODE_GEO"
ERR_SHORT_CODE_USE_CASE = "ERR_SHORT_CODE_USE_CASE"
ERR_CAMPAIGN_RESUBMISSION_LIMIT = "ERR_CAMPAIGN_RESUBMISSION_LIMIT"
ERR_CAMPAIGN_NOT_APPROVED = "ERR_CAMPAIGN_NOT_APPROVED"
ERR_CAMPAIGN_NOT_DEACTIVATABLE = "ERR_CAMPAIGN_NOT_DEACTIVATABLE"

# ─── Number gates ─────────────────────────────────────────────────────────

ERR_NUMBER_NOT_ATTACHED = "ERR_NUMBER_NOT_ATTACHED"
ERR_NUMBER_TYPE_OCCUPIED = "ERR_NUMBER_TYPE_OCCUPIED"
ERR_PORT_REQUIREMENTS = "ERR_PORT_REQUIREMENTS"

# ─── Send gates ───────────────────────────────────────────────────────────

ERR_NO_CONSENT = "ERR_NO_CONSENT"
ERR_THROUGHPUT_EXCEEDED = "ERR_THROUGHPUT_EXCEEDED"
ERR_RECIPIENT_BUSY = "ERR_RECIPIENT_BUSY"
ERR_MESSAGE_NOT_RETRYABLE = "ERR_MESSAGE_NOT_RETRYABLE"

# ─── Internal fee schedule ────────────────────────────────────────────────

ERR_FEE_SCHEDULE = "ERR_FEE_SCHEDULE"

# ─── Catalogue: error identifier -> HTTP status (PRD section 5) ───────────

ERROR_HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_NOT_FOUND: 404,
    ERR_VALIDATION: 400,
    ERR_ACCOUNT_SUSPENDED: 409,
    ERR_ACCOUNT_CLOSED: 409,
    ERR_INVALID_STATE: 409,
    ERR_STALE_VERSION: 412,
    ERR_BRAND_SCORE_TOO_LOW: 409,
    ERR_BRAND_NOT_VERIFIED: 409,
    ERR_BRAND_REVOKED: 409,
    ERR_TOLLFREE_VETTING_INSUFFICIENT: 409,
    ERR_SHORT_CODE_GEO: 422,
    ERR_SHORT_CODE_USE_CASE: 409,
    ERR_CAMPAIGN_RESUBMISSION_LIMIT: 409,
    ERR_CAMPAIGN_NOT_APPROVED: 409,
    ERR_CAMPAIGN_NOT_DEACTIVATABLE: 409,
    ERR_NUMBER_NOT_ATTACHED: 409,
    ERR_NUMBER_TYPE_OCCUPIED: 409,
    ERR_PORT_REQUIREMENTS: 422,
    ERR_NO_CONSENT: 409,
    ERR_THROUGHPUT_EXCEEDED: 429,
    ERR_RECIPIENT_BUSY: 409,
    ERR_MESSAGE_NOT_RETRYABLE: 409,
    ERR_FEE_SCHEDULE: 422,
    ERR_REJECTION_REASON_INVALID: 400,
}

set_error_http_status_map(ERROR_HTTP_STATUS)
