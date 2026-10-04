"""Error classes and error ID constants per PRD section 5."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Authentication required"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Forbidden"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def sod_violation(msg="Segregation of duties violation"):
    return ApiError("ERR_SOD_VIOLATION", msg, 403)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def invalid_state(msg="Invalid state for this transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def client_not_active(msg="Client is not ACTIVE"):
    return ApiError("ERR_CLIENT_NOT_ACTIVE", msg, 409)


def credit_hold_active(msg="Credit hold is active"):
    return ApiError("ERR_CREDIT_HOLD_ACTIVE", msg, 409)


def wire_confirmation_required(msg="Wire confirmation required"):
    return ApiError("ERR_WIRE_CONFIRMATION_REQUIRED", msg, 409)


def poa_required(msg="POA and agency account number required"):
    return ApiError("ERR_POA_REQUIRED", msg, 422)


def registration_not_verified(msg="Registration not verified"):
    return ApiError("ERR_REGISTRATION_NOT_VERIFIED", msg, 422)


def no_verified_jurisdiction(msg="No verified jurisdiction registration"):
    return ApiError("ERR_NO_VERIFIED_JURISDICTION", msg, 422)


def duplicate_deposit(msg="Duplicate deposit for run and jurisdiction"):
    return ApiError("ERR_DUPLICATE_DEPOSIT", msg, 409)


def deposit_exceeds_liability(msg="Deposits exceed run tax liability"):
    return ApiError("ERR_DEPOSIT_EXCEEDS_LIABILITY", msg, 422)


def funds_not_settled(msg="Backing payroll run is not SETTLED"):
    return ApiError("ERR_FUNDS_NOT_SETTLED", msg, 409)


def period_not_closed(msg="Return period not closed"):
    return ApiError("ERR_PERIOD_NOT_CLOSED", msg, 409)


def year_not_closed(msg="Tax year not closed"):
    return ApiError("ERR_YEAR_NOT_CLOSED", msg, 409)


def duplicate_active_statement(msg="Duplicate active wage statement"):
    return ApiError("ERR_DUPLICATE_ACTIVE_STATEMENT", msg, 409)


def open_notice_blocks(msg="Open notice blocks reconciliation"):
    return ApiError("ERR_OPEN_NOTICE_BLOCKS_RECONCILIATION", msg, 409)


def return_not_amendable(msg="Return is not amendable"):
    return ApiError("ERR_RETURN_NOT_AMENDABLE", msg, 409)


def open_obligations(msg="Client has open obligations"):
    return ApiError("ERR_OPEN_OBLIGATIONS", msg, 409)


def unresolved_funding_failures(msg="Unresolved funding failures remain"):
    return ApiError("ERR_UNRESOLVED_FUNDING_FAILURES", msg, 409)


def pending_impounds(msg="Client has pending impounds"):
    return ApiError("ERR_PENDING_IMPOUNDS", msg, 409)
