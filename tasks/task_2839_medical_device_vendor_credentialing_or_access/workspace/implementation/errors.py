"""Error catalogue (PRD section 5).

The HTTP status for a given error_id is fixed: the same identifier always
returns the same status, regardless of which endpoint raised it.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VENDOR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_TIME_RANGE": 400,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_VENDOR_REP_NOT_FOUND": 404,
    "ERR_CREDENTIAL_NOT_FOUND": 404,
    "ERR_SURGICAL_CASE_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_PIR_NOT_FOUND": 404,
    "ERR_APPROVED_PRODUCT_NOT_FOUND": 404,
    "ERR_LOANER_SET_NOT_FOUND": 404,
    "ERR_CHECK_IN_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_STALE_VENDOR_VERSION": 412,
    "ERR_STALE_CASE_VERSION": 412,
    "ERR_REP_ACCESS_REVOKED": 409,
    "ERR_REP_ACCESS_SUSPENDED": 409,
    "ERR_CREDENTIAL_NOT_PENDING": 409,
    "ERR_AUTHORIZATION_NOT_REQUESTED": 409,
    "ERR_AUTHORIZATION_NOT_APPROVED": 409,
    "ERR_CASE_NOT_SCHEDULED": 409,
    "ERR_PIR_INVALID_STATE": 409,
    "ERR_LOANER_SET_INVALID_STATE": 409,
    "ERR_CHECK_IN_NOT_ACTIVE": 409,
    "ERR_ESCORT_NOT_PENDING": 409,
    "ERR_INCIDENT_INVALID_STATE": 409,
    "ERR_APPEAL_INVALID_STATE": 409,
    "ERR_REP_NOT_REVOKED": 409,
    "ERR_REP_CREDENTIALS_NOT_COMPLIANT": 422,
    "ERR_ESCORT_REQUIRED": 422,
    "ERR_BADGE_WINDOW_NOT_OPEN": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_REP_BADGE_WINDOW_CONFLICT": 409,
    "ERR_SPD_BAY_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_AUTHORIZATION": 409,
    "ERR_DUPLICATE_CREDENTIAL": 409,
    "ERR_DUPLICATE_FACILITY_CODE": 409,
    "ERR_DUPLICATE_VENDOR_CODE": 409,
    "ERR_DUPLICATE_CASE_NUMBER": 409,
    "ERR_CHECK_IN_ALREADY_ACTIVE": 409,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_PIR_REVISION_LIMIT": 422,
    "ERR_PRODUCT_NOT_APPROVED": 422,
    "ERR_IMPLANT_REQUIRES_APPROVED_PRODUCT": 422,
    "ERR_VENDOR_ACCESS_QUOTA_EXCEEDED": 422,
    "ERR_VENDOR_FEE_HOLD": 402,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role must both be present and the role must be one of the eight declared names.",
    "ERR_UNAUTHORIZED": "The authenticated role is not permitted to perform this operation.",
    "ERR_VENDOR_SCOPE_VIOLATION": "An entity-backed role may act only on its own rows.",
    "ERR_SEGREGATION_OF_DUTIES": "This decision may not be taken by the user recorded as the counterparty on the same record.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_INVALID_TIME_RANGE": "The supplied pair of instants is not correctly ordered.",
}


class ApiError(Exception):
    """A single catalogued failure."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
