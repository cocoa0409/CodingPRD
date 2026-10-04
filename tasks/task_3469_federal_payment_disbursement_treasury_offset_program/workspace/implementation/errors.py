"""Error catalog (PRD §5) — error ids, HTTP statuses, and raising helpers."""


class ApiError(Exception):
    """Carries the error_id, HTTP status, and human-readable message."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error identifiers (PRD §5, verbatim) --------------------------------------
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_FORBIDDEN_FOR_ROLE = "ERR_FORBIDDEN_FOR_ROLE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_PAYEE_NOT_FOUND = "ERR_PAYEE_NOT_FOUND"
ERR_CREDITOR_NOT_FOUND = "ERR_CREDITOR_NOT_FOUND"
ERR_OFFSET_NOT_FOUND = "ERR_OFFSET_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_STATE_CODE_REQUIRED = "ERR_STATE_CODE_REQUIRED"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_PAYMENT_NOT_EXECUTABLE = "ERR_PAYMENT_NOT_EXECUTABLE"
ERR_OFFSET_NOT_APPLIED = "ERR_OFFSET_NOT_APPLIED"
ERR_APPEAL_LIMIT_REACHED = "ERR_APPEAL_LIMIT_REACHED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_DUE_PROCESS_NOT_COMPLETED = "ERR_DUE_PROCESS_NOT_COMPLETED"
ERR_NOTICE_WINDOW_NOT_ELAPSED = "ERR_NOTICE_WINDOW_NOT_ELAPSED"
ERR_AWG_HEARING_WINDOW_OPEN = "ERR_AWG_HEARING_WINDOW_OPEN"
ERR_DNP_FLAGGED_PAYMENT = "ERR_DNP_FLAGGED_PAYMENT"
ERR_CLAIM_WINDOW_EXPIRED = "ERR_CLAIM_WINDOW_EXPIRED"
ERR_APPEAL_WINDOW_EXPIRED = "ERR_APPEAL_WINDOW_EXPIRED"
ERR_REQUEST_EXPIRED = "ERR_REQUEST_EXPIRED"
ERR_AGREEMENT_OVERLAP = "ERR_AGREEMENT_OVERLAP"
ERR_DNP_WINDOW_OVERLAP = "ERR_DNP_WINDOW_OVERLAP"
ERR_DUPLICATE_TIN = "ERR_DUPLICATE_TIN"
ERR_DUPLICATE_CREDITOR_CODE = "ERR_DUPLICATE_CREDITOR_CODE"
ERR_DUPLICATE_AGENCY_CODE = "ERR_DUPLICATE_AGENCY_CODE"
ERR_PAYEE_TIN_MISMATCH = "ERR_PAYEE_TIN_MISMATCH"
ERR_NO_ACTIVE_POLICY = "ERR_NO_ACTIVE_POLICY"
ERR_AGREEMENT_NOT_ACTIVE = "ERR_AGREEMENT_NOT_ACTIVE"
ERR_NO_RECIPROCAL_AGREEMENT = "ERR_NO_RECIPROCAL_AGREEMENT"
ERR_NO_COLLECTION_AGENCY_AVAILABLE = "ERR_NO_COLLECTION_AGENCY_AVAILABLE"
ERR_REFUND_EXCEEDS_OFFSET = "ERR_REFUND_EXCEEDS_OFFSET"
ERR_COLLECT_EXCEEDS_BALANCE = "ERR_COLLECT_EXCEEDS_BALANCE"
ERR_COLLECT_AMOUNT_ZERO = "ERR_COLLECT_AMOUNT_ZERO"


# --- Raising helpers ------------------------------------------------------------
def err_missing_context(msg="X-User-ID and X-User-Role headers must be present and the role must be declared"):
    return ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400, msg)


def err_forbidden(msg="The caller's role is not permitted on this endpoint"):
    return ApiError(ERR_FORBIDDEN_FOR_ROLE, 403, msg)


def err_segregation(msg="The deciding officer must differ from the operator who executed the offset's payment"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def err_not_found(msg="The referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def err_payee_not_found(msg="payee_id does not exist"):
    return ApiError(ERR_PAYEE_NOT_FOUND, 404, msg)


def err_creditor_not_found(msg="creditor_agency_id does not exist"):
    return ApiError(ERR_CREDITOR_NOT_FOUND, 404, msg)


def err_offset_not_found(msg="offset_id does not exist"):
    return ApiError(ERR_OFFSET_NOT_FOUND, 404, msg)


def err_invalid_request(msg="The request body is invalid"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def err_state_code_required(msg="state_code is required when creditor_type is STATE"):
    return ApiError(ERR_STATE_CODE_REQUIRED, 400, msg)


def err_invalid_state(msg="The resource is in a state where this transition is not defined"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def err_payment_not_executable(msg="Payment is not in EVALUATED status"):
    return ApiError(ERR_PAYMENT_NOT_EXECUTABLE, 409, msg)


def err_offset_not_applied(msg="The offset is not in APPLIED status"):
    return ApiError(ERR_OFFSET_NOT_APPLIED, 409, msg)


def err_appeal_limit_reached(msg="The claim has already been appealed once"):
    return ApiError(ERR_APPEAL_LIMIT_REACHED, 409, msg)


def err_stale_version(msg="The expected version does not match the resource's current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def err_due_process_not_completed(msg="Pre-offset due process has not been attested"):
    return ApiError(ERR_DUE_PROCESS_NOT_COMPLETED, 409, msg)


def err_notice_window_not_elapsed(msg="The 30-day pre-offset notice window has not elapsed"):
    return ApiError(ERR_NOTICE_WINDOW_NOT_ELAPSED, 409, msg)


def err_awg_hearing_window_open(msg="The 15-day garnishment hearing window is still open"):
    return ApiError(ERR_AWG_HEARING_WINDOW_OPEN, 409, msg)


def err_dnp_flagged_payment(msg="The payment is flagged by the do-not-pay screen"):
    return ApiError(ERR_DNP_FLAGGED_PAYMENT, 409, msg)


def err_claim_window_expired(msg="The claim was filed more than 180 days after the offset was applied"):
    return ApiError(ERR_CLAIM_WINDOW_EXPIRED, 409, msg)


def err_appeal_window_expired(msg="The appeal was filed more than 30 days after the decision"):
    return ApiError(ERR_APPEAL_WINDOW_EXPIRED, 409, msg)


def err_request_expired(msg="The reverse-offset request has expired"):
    return ApiError(ERR_REQUEST_EXPIRED, 409, msg)


def err_agreement_overlap(msg="The window overlaps an ACTIVE agreement of the same state with a conflicting direction scope"):
    return ApiError(ERR_AGREEMENT_OVERLAP, 409, msg)


def err_dnp_window_overlap(msg="The interval overlaps another ACTIVE do-not-pay record for the same TIN and list source"):
    return ApiError(ERR_DNP_WINDOW_OVERLAP, 409, msg)


def err_duplicate_tin(msg="A payee with this TIN is already registered"):
    return ApiError(ERR_DUPLICATE_TIN, 409, msg)


def err_duplicate_creditor_code(msg="A creditor agency with this code is already registered"):
    return ApiError(ERR_DUPLICATE_CREDITOR_CODE, 409, msg)


def err_duplicate_agency_code(msg="A collection agency with this code is already registered"):
    return ApiError(ERR_DUPLICATE_AGENCY_CODE, 409, msg)


def err_payee_tin_mismatch(msg="payee_tin does not equal the TIN of the referenced payee"):
    return ApiError(ERR_PAYEE_TIN_MISMATCH, 422, msg)


def err_no_active_policy(msg="No ACTIVE exemption policy exists for the payment type"):
    return ApiError(ERR_NO_ACTIVE_POLICY, 409, msg)


def err_agreement_not_active(msg="No ACTIVE reciprocal agreement covers the creditor's state in the FED_TO_STATE scope"):
    return ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409, msg)


def err_no_reciprocal_agreement(msg="No ACTIVE reciprocal agreement covers the state in the STATE_TO_FED scope"):
    return ApiError(ERR_NO_RECIPROCAL_AGREEMENT, 409, msg)


def err_no_collection_agency_available(msg="No collection agency can accept another open cross-servicing action"):
    return ApiError(ERR_NO_COLLECTION_AGENCY_AVAILABLE, 409, msg)


def err_refund_exceeds_offset(msg="claimed_amount_cents exceeds the offset amount"):
    return ApiError(ERR_REFUND_EXCEEDS_OFFSET, 422, msg)


def err_collect_exceeds_balance(msg="remitted_amount_cents exceeds the debt's current balance"):
    return ApiError(ERR_COLLECT_EXCEEDS_BALANCE, 422, msg)


def err_collect_amount_zero(msg="The computed garnishment amount is zero"):
    return ApiError(ERR_COLLECT_AMOUNT_ZERO, 422, msg)
