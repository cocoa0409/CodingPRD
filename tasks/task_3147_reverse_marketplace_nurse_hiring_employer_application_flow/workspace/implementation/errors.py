"""Error types and catalog for the reverse nurse marketplace API."""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DEADLINE_PASSED = "ERR_DEADLINE_PASSED"
ERR_CANDIDATE_CONFIDENTIAL = "ERR_CANDIDATE_CONFIDENTIAL"
ERR_CREDENTIALS_INCOMPLETE = "ERR_CREDENTIALS_INCOMPLETE"
ERR_TERMS_MISMATCH = "ERR_TERMS_MISMATCH"
ERR_INTERVIEW_CONFLICT = "ERR_INTERVIEW_CONFLICT"
ERR_NO_OPENINGS = "ERR_NO_OPENINGS"
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"
ERR_STALE_NURSE_VERSION = "ERR_STALE_NURSE_VERSION"
ERR_STALE_REQUISITION_VERSION = "ERR_STALE_REQUISITION_VERSION"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_LICENSE_EXPIRED = "ERR_LICENSE_EXPIRED"
ERR_NURSE_HAS_LIVE_APPLICATIONS = "ERR_NURSE_HAS_LIVE_APPLICATIONS"
ERR_PLACEMENT_GUARANTEE_EXPIRED = "ERR_PLACEMENT_GUARANTEE_EXPIRED"
ERR_REVIEW_NOTE_REQUIRED = "ERR_REVIEW_NOTE_REQUIRED"
ERR_UNIT_DAY_CAPACITY = "ERR_UNIT_DAY_CAPACITY"


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden(msg="Role not permitted or ownership mismatch"):
    return ApiError(ERR_FORBIDDEN, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg="Entity not in a state permitting this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def deadline_passed(msg="Deadline has passed"):
    return ApiError(ERR_DEADLINE_PASSED, 409, msg)


def candidate_confidential(msg="Employer is excluded by the nurse's confidentiality list"):
    return ApiError(ERR_CANDIDATE_CONFIDENTIAL, 403, msg)


def credentials_incomplete(msg="Credential gates not satisfied"):
    return ApiError(ERR_CREDENTIALS_INCOMPLETE, 422, msg)


def terms_mismatch(msg="Terms constraint violated"):
    return ApiError(ERR_TERMS_MISMATCH, 422, msg)


def interview_conflict(msg="Interview collides with an existing scheduled interview"):
    return ApiError(ERR_INTERVIEW_CONFLICT, 409, msg)


def no_openings(msg="No openings remaining or employer suspended"):
    return ApiError(ERR_NO_OPENINGS, 409, msg)


def duplicate_resource(msg="Duplicate resource"):
    return ApiError(ERR_DUPLICATE_RESOURCE, 409, msg)


def stale_nurse_version(msg="expected_nurse_version is stale"):
    return ApiError(ERR_STALE_NURSE_VERSION, 412, msg)


def stale_requisition_version(msg="expected_requisition_version is stale"):
    return ApiError(ERR_STALE_REQUISITION_VERSION, 412, msg)


def validation(msg="Malformed body or field out of range"):
    return ApiError(ERR_VALIDATION, 400, msg)


def license_expired(msg="License or certification expiry is not strictly after the current date"):
    return ApiError(ERR_LICENSE_EXPIRED, 422, msg)


def nurse_has_live_applications(msg="Nurse has live applications"):
    return ApiError(ERR_NURSE_HAS_LIVE_APPLICATIONS, 409, msg)


def placement_guarantee_expired(msg="Placement guarantee window has closed"):
    return ApiError(ERR_PLACEMENT_GUARANTEE_EXPIRED, 409, msg)


def review_note_required(msg="review_note or rejection_reason is required"):
    return ApiError(ERR_REVIEW_NOTE_REQUIRED, 400, msg)


def unit_day_capacity(msg="Unit day interview capacity exceeded"):
    return ApiError(ERR_UNIT_DAY_CAPACITY, 409, msg)
