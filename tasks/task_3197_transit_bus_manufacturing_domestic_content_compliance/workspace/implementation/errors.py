"""Error types and helpers."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Missing required field or malformed value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="State machine has no transition for this trigger from the current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected_contract_version does not match current Contract.version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_sod(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 422)


def err_domestic_threshold(msg="Domestic content below threshold"):
    return ApiError("ERR_DOMESTIC_CONTENT_BELOW_THRESHOLD", msg, 422)


def err_certificate_missing(msg="Bus has no ISSUED ComplianceCertificate"):
    return ApiError("ERR_CERTIFICATE_MISSING", msg, 422)


def err_accessibility(msg="Federally funded bus configuration lacks WHEELCHAIR_LIFT"):
    return ApiError("ERR_ACCESSIBILITY_SAFETY", msg, 422)


def err_schedule_conflict(msg="Schedule conflict"):
    return ApiError("ERR_SCHEDULE_CONFLICT", msg, 409)


def err_duplicate(msg="Uniqueness violated"):
    return ApiError("ERR_DUPLICATE", msg, 409)


def err_deadline(msg="Action attempted after its deadline"):
    return ApiError("ERR_DEADLINE_PASSED", msg, 422)


def err_audit_incomplete(msg="Contract activation requires a COMPLETED PASS PRE_AWARD audit"):
    return ApiError("ERR_AUDIT_INCOMPLETE", msg, 409)


def err_audit_precondition(msg="Audit completion preconditions unmet"):
    return ApiError("ERR_AUDIT_PRECONDITION", msg, 422)


def err_kit_incomplete(msg="Production start attempted while slot is NOT_KITTED"):
    return ApiError("ERR_KIT_INCOMPLETE", msg, 409)


def err_referential(msg="Referenced entity missing or in unusable state"):
    return ApiError("ERR_REFERENTIAL_INTEGRITY", msg, 422)


def err_fiscal(msg="Non-positive quantity/price or stock quantity below reserved"):
    return ApiError("ERR_FISCAL_VIOLATION", msg, 422)


def err_agency_suspended(msg="Agency is SUSPENDED"):
    return ApiError("ERR_AGENCY_SUSPENDED", msg, 409)


def err_review_loop(msg="Warranty claim revision loop exhausted"):
    return ApiError("ERR_REVIEW_LOOP_EXHAUSTED", msg, 409)


def err_inspection_defects(msg="FAIL inspection requires non-empty defects"):
    return ApiError("ERR_INSPECTION_DEFECTS_REQUIRED", msg, 400)


def err_validation(msg="Business validation failure"):
    return ApiError("ERR_VALIDATION", msg, 422)
