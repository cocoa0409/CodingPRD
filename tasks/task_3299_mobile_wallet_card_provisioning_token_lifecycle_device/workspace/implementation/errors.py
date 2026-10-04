# =============================================================================
# Error catalog — ids and HTTP statuses from the scaffold's error table
# =============================================================================

ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_ISSUER_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_TOKEN_NOT_FOUND": 404,
    "ERR_CARD_ACCOUNT_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_OPERATOR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_INVALID_TRANSITION": 409,
    "ERR_IDEMPOTENCY_CONFLICT": 409,
    "ERR_VERSION_CONFLICT": 412,
    "ERR_DEVICE_UNSECURED": 409,
    "ERR_DEVICE_LOST": 409,
    "ERR_TOKEN_NOT_ACTIVE": 409,
    "ERR_CARD_ACCOUNT_RESTRICTED": 409,
    "ERR_CARD_HAS_OPEN_DISPUTES": 409,
    "ERR_PROVISIONING_SESSION_EXPIRED": 409,
    "ERR_OTP_MISMATCH": 409,
    "ERR_ISSUER_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_REQUIRED": 409,
    "ERR_AGREEMENT_OVERLAP": 409,
    "ERR_TERMS_VALIDATION_FAILED": 422,
    "ERR_AUTHENTICATION_REQUIRED": 422,
    "ERR_AUTH_AMOUNT_EXCEEDS_CAP": 422,
    "ERR_PROGRAM_AMOUNT_EXCEEDS_CAP": 422,
    "ERR_EXPRESS_TRANSIT_NOT_SUPPORTED": 422,
    "ERR_TRANSIT_NOT_ALLOWED": 422,
    "ERR_PROGRAM_NOT_ACTIVE": 409,
    "ERR_PROGRAM_INELIGIBLE": 409,
    "ERR_DISPUTE_AMOUNT_MISMATCH": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def missing_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
        "X-User-ID and X-User-Role headers must be present and well-formed",
    )


def forbidden(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg)


def validation(msg="Payload schema violation"):
    return ApiError("ERR_VALIDATION", msg)


def not_found(error_id, msg):
    return ApiError(error_id, msg)
