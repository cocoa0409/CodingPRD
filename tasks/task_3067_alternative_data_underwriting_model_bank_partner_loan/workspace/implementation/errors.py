"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Missing or malformed X-User-ID / X-User-Role headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def forbidden(msg="Role not permitted to call this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def referenced_not_found(msg="Referenced resource not found"):
    return ApiError("ERR_REFERENCED_NOT_FOUND", msg, 404)


def invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def validation(msg="Schema violation"):
    return ApiError("ERR_VALIDATION", msg, 400)


def app_invalid_state(msg="Application not in a state that permits this transition"):
    return ApiError("ERR_APPLICATION_INVALID_STATE", msg, 409)


def model_invalid_state(msg="ModelVersion not in a state that permits this transition"):
    return ApiError("ERR_MODEL_INVALID_STATE", msg, 409)


def model_locked(msg="ModelVersion is no longer in DRAFT"):
    return ApiError("ERR_MODEL_LOCKED", msg, 409)


def model_already_active(msg="Another ModelVersion is already ACTIVE"):
    return ApiError("ERR_MODEL_ALREADY_ACTIVE", msg, 409)


def model_has_open_applications(msg="Model has non-terminal applications"):
    return ApiError("ERR_MODEL_HAS_OPEN_APPLICATIONS", msg, 409)


def no_active_model(msg="No ACTIVE model exists"):
    return ApiError("ERR_NO_ACTIVE_MODEL", msg, 409)


def partner_invalid_state(msg="Partner not in a state that permits this transition"):
    return ApiError("ERR_PARTNER_INVALID_STATE", msg, 409)


def partner_holds_loans(msg="Partner holds live loans"):
    return ApiError("ERR_PARTNER_HOLDS_LOANS", msg, 409)


def credit_box_invalid_state(msg="CreditBox not in a state that permits this transition"):
    return ApiError("ERR_CREDIT_BOX_INVALID_STATE", msg, 409)


def credit_box_not_in_window(msg="Logical clock outside credit box activation window"):
    return ApiError("ERR_CREDIT_BOX_NOT_IN_WINDOW", msg, 409)


def verification_invalid_state(msg="Verification not in a state that permits this action"):
    return ApiError("ERR_VERIFICATION_INVALID_STATE", msg, 409)


def loan_invalid_state(msg="Loan not in a state that permits this servicing action"):
    return ApiError("ERR_LOAN_INVALID_STATE", msg, 409)


def pool_invalid_state(msg="SecuritizationPool not OPEN for this action"):
    return ApiError("ERR_POOL_INVALID_STATE", msg, 409)


def fairness_gate_blocking(msg="Fairness gate blocking activation"):
    return ApiError("ERR_FAIRNESS_GATE_BLOCKING", msg, 409)


def exclusion_review_open(msg="A VARIABLE_EXCLUSION review is still PENDING"):
    return ApiError("ERR_EXCLUSION_REVIEW_OPEN", msg, 409)


def segregation_of_duties(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 409)


def payment_invalid(msg="Payment amount non-positive or loan not in a payable state"):
    return ApiError("ERR_PAYMENT_INVALID", msg, 422)


def stale_version(msg="Stale expected version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)
