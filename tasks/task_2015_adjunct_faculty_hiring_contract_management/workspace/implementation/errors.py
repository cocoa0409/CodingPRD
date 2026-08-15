"""Error classes and error ID constants for the Adjunct Faculty Contracts API.

Error identifiers and HTTP statuses come straight from SCAFFOLD.yaml Table 6
and PRD Section 5.
"""


class ApiError(Exception):
    """Exception carrying the exact error_id and HTTP status of the catalog."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED_ROLE = "ERR_UNAUTHORIZED_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_POSTING_NOT_OPEN = "ERR_POSTING_NOT_OPEN"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_CREDENTIALS_INCOMPLETE = "ERR_CREDENTIALS_INCOMPLETE"
ERR_COMPLIANCE_INCOMPLETE = "ERR_COMPLIANCE_INCOMPLETE"
ERR_DUPLICATE = "ERR_DUPLICATE"
ERR_INVALID_DATE_RANGE = "ERR_INVALID_DATE_RANGE"
ERR_SCHEDULE_OVERLAP = "ERR_SCHEDULE_OVERLAP"
ERR_PAYROLL_PERIOD_OVERLAP = "ERR_PAYROLL_PERIOD_OVERLAP"
ERR_CANCELLATION_POLICY = "ERR_CANCELLATION_POLICY"
ERR_CONTRACT_REFERENCE_INVALID = "ERR_CONTRACT_REFERENCE_INVALID"
ERR_LOAD_CAP_EXCEEDED = "ERR_LOAD_CAP_EXCEEDED"
ERR_PAYROLL_CLOSE_ORDER = "ERR_PAYROLL_CLOSE_ORDER"
ERR_STALE_FACULTY_VERSION = "ERR_STALE_FACULTY_VERSION"
ERR_REFERENCE_IN_USE = "ERR_REFERENCE_IN_USE"
ERR_REVISION_LIMIT = "ERR_REVISION_LIMIT"


def unauthenticated(message="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, message)


def unauthorized_role(message="Acting role is not authorized for this endpoint"):
    return ApiError(ERR_UNAUTHORIZED_ROLE, 403, message)


def not_found(message="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_request(message="Request body failed schema validation"):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def invalid_state(message="Requested transition does not exist from the current state"):
    return ApiError(ERR_INVALID_STATE, 409, message)


def posting_not_open(message="Posting is not OPEN or the filing window has passed"):
    return ApiError(ERR_POSTING_NOT_OPEN, 409, message)


def segregation_of_duties(message="Approving reviewer verified a credential on this application"):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, message)


def credentials_incomplete(message="Credential completeness check failed for approval"):
    return ApiError(ERR_CREDENTIALS_INCOMPLETE, 422, message)


def compliance_incomplete(message="Compliance gate failed"):
    return ApiError(ERR_COMPLIANCE_INCOMPLETE, 422, message)


def duplicate(message="Uniqueness constraint violated"):
    return ApiError(ERR_DUPLICATE, 409, message)


def invalid_date_range(message="Date coherence rule violated"):
    return ApiError(ERR_INVALID_DATE_RANGE, 422, message)


def schedule_overlap(message="Overlapping PUBLISHED rate schedule exists for department and tier"):
    return ApiError(ERR_SCHEDULE_OVERLAP, 409, message)


def payroll_period_overlap(message="New payroll period overlaps an existing non-CLOSED period"):
    return ApiError(ERR_PAYROLL_PERIOD_OVERLAP, 409, message)


def cancellation_policy(message="LOW_ENROLLMENT cancellation policy not satisfied"):
    return ApiError(ERR_CANCELLATION_POLICY, 422, message)


def contract_reference_invalid(message="Contract issuance reference check failed"):
    return ApiError(ERR_CONTRACT_REFERENCE_INVALID, 422, message)


def load_cap_exceeded(message="Prospective load exceeds load cap plus overage allowance"):
    return ApiError(ERR_LOAD_CAP_EXCEEDED, 422, message)


def payroll_close_order(message="Payroll periods must close in chronological order"):
    return ApiError(ERR_PAYROLL_CLOSE_ORDER, 422, message)


def stale_faculty_version(message="expected_faculty_version does not match current faculty version"):
    return ApiError(ERR_STALE_FACULTY_VERSION, 412, message)


def reference_in_use(message="Resource is still referenced by live records"):
    return ApiError(ERR_REFERENCE_IN_USE, 409, message)


def revision_limit(message="Revision loop bound (3) reached"):
    return ApiError(ERR_REVISION_LIMIT, 422, message)
