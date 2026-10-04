"""Error catalog: every error_id from the scaffold's error table with its HTTP status."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_DELIVERY_NOT_FOUND": 404,
    "ERR_OUTCOME_REPORT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INTAKE_NOT_ROUTED": 409,
    "ERR_GRANT_FROZEN": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_CONFIDENTIALITY_SCOPE_DENIED": 403,
    "ERR_FAITH_BASED_ACTIVITY_PROHIBITED": 422,
    "ERR_NONDISCRIMINATION_VIOLATION": 422,
    "ERR_ELIGIBILITY_NOT_ESTABLISHED": 409,
    "ERR_CLIENT_ALREADY_ENROLLED": 409,
    "ERR_AUTHORIZATION_PERIOD_OVERLAP": 409,
    "ERR_OUTCOME_PERIOD_OVERLAP": 409,
    "ERR_INKIND_HOURS_EXCEEDED": 422,
    "ERR_PROGRAM_CAPACITY_EXCEEDED": 409,
    "ERR_ZERO_UNITS": 422,
    "ERR_NO_ACTIVE_AUTHORIZATION": 409,
    "ERR_ALLOCATION_EXCEEDS_AWARD": 409,
    "ERR_ADMIN_RATE_EXCEEDED": 422,
    "ERR_DUPLICATE_SERVICE_BILLING": 409,
    "ERR_MATCH_REQUIREMENT_UNMET": 422,
    "ERR_INKIND_VALUATION_INVALID": 422,
    # Internal only: malformed request body / unknown route. Not part of the
    # declared catalog; no declared condition maps to it.
    "ERR_BAD_REQUEST": 422,
}


class ApiError(Exception):
    """Carries the declared error_id plus the human-readable message."""

    def __init__(self, error_id, message="", http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
