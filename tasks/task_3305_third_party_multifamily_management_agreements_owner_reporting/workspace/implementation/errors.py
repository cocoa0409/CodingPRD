"""Error types and error catalog for the management agreements API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def missing_user_context(msg="X-User-ID or X-User-Role header missing or malformed"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def forbidden_for_role(msg="Caller role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", msg, 403)


def not_found(msg="Path-identified resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def invalid_state_transition(msg="Requested transition is not defined from the resource's current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", msg, 409)


def stale_version(msg="expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def owner_not_active(msg="Agreement activation requires Owner.status == ACTIVE"):
    return ApiError("ERR_OWNER_NOT_ACTIVE", msg, 409)


def agreement_not_active(msg="Onboarding activation requires an ACTIVE ManagementAgreement"):
    return ApiError("ERR_AGREEMENT_NOT_ACTIVE", msg, 409)


def pending_owner_decision(msg="A Budget is SUBMITTED awaiting owner decision"):
    return ApiError("ERR_PENDING_OWNER_DECISION", msg, 409)


def no_resident_data(msg="Resident-data verification requires at least one Resident row"):
    return ApiError("ERR_NO_RESIDENT_DATA", msg, 409)


def vendor_contracts_pending(msg="Vendor review cannot complete while contracts remain PENDING"):
    return ApiError("ERR_VENDOR_CONTRACTS_PENDING", msg, 409)


def open_claims_block_exit(msg="Termination cannot complete while Claims are OPEN or UNDER_REVIEW"):
    return ApiError("ERR_OPEN_CLAIMS_BLOCK_EXIT", msg, 409)


def reforecast_requires_base(msg="REFORECAST budget must supersede an APPROVED budget"):
    return ApiError("ERR_REFORECAST_REQUIRES_APPROVED_BASE", msg, 409)


def sod_violation(msg="Budget approver/rejecter must differ from the submitter"):
    return ApiError("ERR_SOD_VIOLATION", msg, 409)


def pricing_window_overlap(msg="A PUBLISHED recommendation covers an overlapping window"):
    return ApiError("ERR_PRICING_WINDOW_OVERLAP", msg, 409)


def override_band_exceeded(msg="Override rent deviates from recommendation by more than MAX_OVERRIDE_BAND_PCT"):
    return ApiError("ERR_OVERRIDE_BAND_EXCEEDED", msg, 409)


def statement_period_open(msg="Statement cannot close before its period month has ended"):
    return ApiError("ERR_STATEMENT_PERIOD_OPEN", msg, 409)


def books_locked(msg="Statement cannot be restated after report packages are DELIVERED"):
    return ApiError("ERR_BOOKS_LOCKED", msg, 409)


def distribution_window_missed(msg="Owner report delivered after distribution day plus grace"):
    return ApiError("ERR_DISTRIBUTION_WINDOW_MISSED", msg, 409)


def lender_report_overdue(msg="Lender report not delivered by month-end"):
    return ApiError("ERR_LENDER_REPORT_OVERDUE", msg, 409)


def incident_outside_term(msg="Manager-indemnified claim has incident_date outside the term"):
    return ApiError("ERR_INCIDENT_OUTSIDE_TERM", msg, 409)


def reserve_outstanding(msg="OPEN claim cannot be closed while reserved_amount_cents > 0"):
    return ApiError("ERR_RESERVE_OUTSTANDING", msg, 409)
