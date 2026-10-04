"""Error identifiers and the API exception type.

Every identifier here appears verbatim in PRD section 5 and SCAFFOLD section 1.6.
"""


class ApiError(Exception):
    """An error that maps to the standard error envelope."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def bad_request(msg="The request body is malformed."):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def unauthenticated(msg="X-User-ID and X-User-Role headers are required."):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def unauthorized(msg="The acting role may not call this operation."):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def not_found(error_id, msg):
    return ApiError(error_id, msg, 404)


def invalid_state(msg="The resource is not in a state from which this transition exists."):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def separation_violation(msg="Research independence rules forbid this operation."):
    return ApiError("ERR_SEPARATION_OF_DUTIES_VIOLATION", msg, 403)


def stale_version(msg="The supplied expected version is stale."):
    return ApiError("ERR_STALE_VERSION", msg, 412)


# --- not-found family (PRD 2.11) -------------------------------------------
CLIENT_ACCOUNT_NOT_FOUND = "ERR_CLIENT_ACCOUNT_NOT_FOUND"
SEAT_NOT_FOUND = "ERR_SEAT_NOT_FOUND"
ANALYST_NOT_FOUND = "ERR_ANALYST_NOT_FOUND"
INQUIRY_NOT_FOUND = "ERR_INQUIRY_NOT_FOUND"
DOCUMENT_NOT_FOUND = "ERR_DOCUMENT_NOT_FOUND"
VENDOR_NOT_FOUND = "ERR_VENDOR_NOT_FOUND"
VENDOR_INCLUSION_NOT_FOUND = "ERR_VENDOR_INCLUSION_NOT_FOUND"
BRIEFING_NOT_FOUND = "ERR_BRIEFING_NOT_FOUND"
SALES_RELATIONSHIP_NOT_FOUND = "ERR_SALES_RELATIONSHIP_NOT_FOUND"
CONFERENCE_EVENT_NOT_FOUND = "ERR_CONFERENCE_EVENT_NOT_FOUND"
SPONSORSHIP_NOT_FOUND = "ERR_SPONSORSHIP_NOT_FOUND"
