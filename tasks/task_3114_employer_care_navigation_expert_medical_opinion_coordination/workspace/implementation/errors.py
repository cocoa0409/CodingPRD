"""Error classes and error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# HTTP status per error id (from scaffold §1.6 / PRD §5)
ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_MEMBER_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_MEMBER_INELIGIBLE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_CONSENT_REQUIRED": 409,
    "ERR_CONSENT_ALREADY_ACTIVE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DISCIPLINE_MISMATCH": 403,
    "ERR_NOT_ASSIGNED_NAVIGATOR": 403,
    "ERR_NOT_ASSIGNED_REVIEWER": 403,
    "ERR_NOT_ASSIGNED_COMPILER": 403,
    "ERR_COVERAGE_OVERLAP": 409,
    "ERR_SLOT_CONFLICT": 409,
    "ERR_PROVIDER_DAY_CAPACITY": 422,
    "ERR_NO_PROVIDER_MATCH": 422,
    "ERR_DUPLICATE_SNAPSHOT": 409,
    "ERR_DUPLICATE_AUTHORIZATION": 409,
    "ERR_DUPLICATE_MEMBER_REF": 409,
    "ERR_RECORD_NOT_READY": 409,
    "ERR_RECORDS_INSUFFICIENT": 422,
    "ERR_AUTHORIZATION_REQUIRED": 409,
    "ERR_CLAIM_ALREADY_ADJUDICATED": 409,
    "ERR_CLAIM_NOT_ADJUDICATED": 409,
    "ERR_NO_LINE_ERRORS": 422,
    "ERR_SETTLEMENT_EXCEEDS_BILLED": 422,
    "ERR_NEGOTIATION_ROUND_EXCEEDED": 422,
    "ERR_APPOINTMENT_NOT_DUE": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_RETRY_EXHAUSTED": 422,
    "ERR_STALE_VERSION": 412,
}


def fail(error_id, message):
    raise ApiError(error_id, ERR[error_id], message)
