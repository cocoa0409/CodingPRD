"""Error catalogue for the Digital MSK Program Enrollment & Outcome Fees API.

Every error id declared in the scaffold / PRD catalogue carries its own HTTP
status.  The ids and statuses below are transcribed verbatim from the
specification (SCAFFOLD.yaml §1.6 + PRD §5).
"""


class ApiError(Exception):
    """An error that is rendered through the standard error envelope."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status or ERROR_STATUS.get(error_id, 500)


# error_id -> HTTP status (SCAFFOLD.yaml §1.6, PRD §5)
ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_CLINICIAN_DUAL_ROLE": 403,
    "ERR_TRANSITION_REVIEWER_MISMATCH": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_VITALS_OUT_OF_RANGE": 422,
    "ERR_PAIN_WORSENED": 422,
    "ERR_APPOINTMENT_OVERLAP": 422,
    "ERR_CLINICIAN_CAPACITY_EXCEEDED": 422,
    "ERR_INVALID_REFERENCE": 422,
    "ERR_CLIENT_NOT_ACTIVE": 422,
    "ERR_INVOICE_UNRECONCILED": 422,
    "ERR_DROPOUT_CRITERIA_NOT_MET": 422,
    "ERR_PATIENT_UNDERAGE": 422,
    "ERR_WEEK_ALREADY_SCHEDULED": 409,
    "ERR_FILE_PERIOD_REGRESSION": 409,
    "ERR_MEASUREMENT_WEEK_DUPLICATE": 409,
    "ERR_DUPLICATE_SAVINGS_ATTRIBUTION": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ENROLLMENT_NOT_IN_REVIEW": 409,
    "ERR_REVIEW_ALREADY_CONDUCTED": 409,
    "ERR_TRANSITION_NOT_PENDING": 409,
    "ERR_MEASUREMENT_FINALIZED": 409,
    "ERR_MEASUREMENT_WINDOW_OPEN": 409,
    "ERR_MEASUREMENT_LIMIT_REACHED": 409,
    "ERR_NO_FINALIZED_MEASUREMENT": 409,
    "ERR_DROPOUT_WINDOW_CLOSED": 409,
    "ERR_OUTREACH_WINDOW_CLOSED": 409,
    "ERR_OUTREACH_WEEK_LAPSED": 409,
    "ERR_OUTREACH_CONTACT_LIMIT": 409,
    "ERR_INVOICE_ALREADY_VOID": 409,
    "ERR_SESSION_ACTIVATION_FAILED": 409,
    "ERR_SESSION_WEEK_CLOSED": 409,
    "ERR_CLAIM_LINE_WINDOW_CLOSED": 409,
    "ERR_STALE_VERSION": 412,
}


def missing_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
        "X-User-ID and X-User-Role are required, and X-User-Role must name a role "
        "declared by this API.",
    )


def forbidden_role(role, operation):
    return ApiError(
        "ERR_FORBIDDEN_ROLE",
        "Role %s is not permitted to perform %s." % (role, operation),
    )


def not_found(what):
    return ApiError("ERR_RESOURCE_NOT_FOUND", "%s does not exist." % what)


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", message)


def invalid_reference(message):
    return ApiError("ERR_INVALID_REFERENCE", message)