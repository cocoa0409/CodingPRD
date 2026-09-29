"""Error catalogue (PRD 5) and the exception type carrying it."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_NOT_ASSIGNED_VERIFIER": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_PRODUCER_NOT_FOUND": 404,
    "ERR_SKU_NOT_FOUND": 404,
    "ERR_STATE_PROGRAM_NOT_FOUND": 404,
    "ERR_REPORTING_PERIOD_NOT_FOUND": 404,
    "ERR_PRO_NOT_FOUND": 404,
    "ERR_FEE_SCHEDULE_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_REPORT_NOT_FOUND": 404,
    "ERR_REPORT_LINE_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_REGISTRATION_NOT_ACTIVE": 409,
    "ERR_FEE_SCHEDULE_NOT_PUBLISHED": 409,
    "ERR_REPORT_NOT_IN_DRAFT": 409,
    "ERR_REPORT_NOT_UNDER_VERIFICATION": 409,
    "ERR_STALE_PRO_VERSION": 412,
    "ERR_STALE_REGISTRATION_VERSION": 412,
    # business safety
    "ERR_OBLIGATION_NOT_DETERMINED": 409,
    "ERR_DETERMINATION_STALE": 409,
    "ERR_PRODUCER_NOT_OBLIGATED": 422,
    "ERR_EXEMPT_REGISTRATION_CANNOT_REPORT": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_VERIFIER_ROTATION_REQUIRED": 422,
    "ERR_VERIFICATION_REQUIRED": 409,
    # referential
    "ERR_PERIOD_PROGRAM_MISMATCH": 422,
    "ERR_SKU_PRODUCER_MISMATCH": 422,
    "ERR_FEE_SCHEDULE_PRO_MISMATCH": 422,
    "ERR_FEE_SCHEDULE_PROGRAM_MISMATCH": 422,
    "ERR_MEMBERSHIP_REGISTRATION_MISMATCH": 422,
    "ERR_MATERIAL_RATE_MISSING": 422,
    # constraints
    "ERR_DUPLICATE_REGISTRATION": 409,
    "ERR_DUPLICATE_REPORT_FOR_PERIOD": 409,
    "ERR_DUPLICATE_REPORT_LINE": 409,
    "ERR_PERIOD_WINDOW_OVERLAP": 409,
    "ERR_FEE_SCHEDULE_EFFECTIVE_OVERLAP": 409,
    "ERR_FEE_TIER_DISCONTINUOUS": 422,
    "ERR_FEE_SCHEDULE_HAS_NO_RATES": 422,
    "ERR_SKU_HAS_NO_COMPONENTS": 422,
    "ERR_PRODUCER_HAS_NO_ACTIVE_SKUS": 422,
    "ERR_REPORT_HAS_NO_LINES": 422,
    "ERR_ENGAGEMENT_ALREADY_OPEN": 409,
    "ERR_VERIFIER_CAPACITY_EXCEEDED": 409,
    "ERR_REGISTRATION_HAS_OPEN_REPORTS": 409,
    # temporal
    "ERR_INVALID_FIELDWORK_WINDOW": 422,
    "ERR_REGISTRATION_DEADLINE_PASSED": 422,
    "ERR_SUBMISSION_WINDOW_NOT_OPEN": 422,
    "ERR_SUBMISSION_WINDOW_CLOSED": 422,
    "ERR_CORRECTION_WINDOW_EXPIRED": 422,
    "ERR_CORRECTION_WINDOW_OPEN": 409,
    "ERR_FEE_SCHEDULE_NOT_EFFECTIVE_FOR_PERIOD": 422,
    # fiscal
    "ERR_NO_ACTIVE_MEMBERSHIP": 402,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 409,
    "ERR_MEMBERSHIP_FEE_AMOUNT_MISMATCH": 422,
    "ERR_MEMBERSHIP_FEE_OUTSTANDING": 402,
    "ERR_INVOICE_NOT_ISSUED": 409,
    "ERR_FINDINGS_NOTE_REQUIRED": 422,
    # not part of the catalogue: unknown route fallback
    "ERR_NOT_FOUND": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the role is not recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the target resource.",
    "ERR_NOT_ASSIGNED_VERIFIER": "Only the engagement's assigned verifier may perform this action.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_INVALID_STATE": "The resource's current state does not permit this transition.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
