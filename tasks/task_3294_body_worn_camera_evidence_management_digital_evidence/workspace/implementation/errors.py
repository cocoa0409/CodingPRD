class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unrecognized identity headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted for this endpoint, or ownership check failed"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_validation(msg="Field shape or constraint violation"):
    return ApiError("ERR_VALIDATION", 422, msg)


def err_invalid_state(msg="Resource is not in a state that permits this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="expected_case_version does not match the case's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_policy_already_active(msg="Another policy is already ACTIVE for this agency"):
    return ApiError("ERR_POLICY_ALREADY_ACTIVE", 409, msg)


def err_plan_not_later(msg="New plan's effective_from_month is not strictly later than the current ACTIVE plan's"):
    return ApiError("ERR_PLAN_NOT_LATER", 409, msg)


def err_device_still_assigned(msg="Officer still has a device assigned"):
    return ApiError("ERR_DEVICE_STILL_ASSIGNED", 409, msg)


def err_lead_cases_open(msg="Officer is lead on an OPEN or UNDER_REVIEW case"):
    return ApiError("ERR_LEAD_CASES_OPEN", 409, msg)


def err_officer_not_active(msg="Target officer is not ACTIVE"):
    return ApiError("ERR_OFFICER_NOT_ACTIVE", 409, msg)


def err_officer_already_has_device(msg="Target officer already has an ASSIGNED device"):
    return ApiError("ERR_OFFICER_ALREADY_HAS_DEVICE", 409, msg)


def err_device_unhealthy(msg="Device health_status is not HEALTHY"):
    return ApiError("ERR_DEVICE_UNHEALTHY", 409, msg)


def err_battery_too_low(msg="Device battery_pct is below 20"):
    return ApiError("ERR_BATTERY_TOO_LOW", 409, msg)


def err_device_not_docked(msg="Device is not DOCKED"):
    return ApiError("ERR_DEVICE_NOT_DOCKED", 409, msg)


def err_category_required(msg="A category is required by the active agency policy"):
    return ApiError("ERR_CATEGORY_REQUIRED", 422, msg)


def err_integrity_failed(msg="Recording is in INTEGRITY_FAILED quarantine"):
    return ApiError("ERR_INTEGRITY_FAILED", 409, msg)


def err_case_empty(msg="Case has no linked evidence"):
    return ApiError("ERR_CASE_EMPTY", 409, msg)


def err_evidence_not_ready(msg="A LINKED recording is not in ACTIVE or RETENTION_DUE"):
    return ApiError("ERR_EVIDENCE_NOT_READY", 409, msg)


def err_reviews_outstanding(msg="A LINKED recording is still PENDING_REVIEW"):
    return ApiError("ERR_REVIEWS_OUTSTANDING", 409, msg)


def err_active_share_grants(msg="An ACTIVE share grant exists on the case"):
    return ApiError("ERR_ACTIVE_SHARE_GRANTS", 409, msg)


def err_legal_hold_active(msg="An ACTIVE case-scoped legal hold exists on the case"):
    return ApiError("ERR_LEGAL_HOLD_ACTIVE", 409, msg)


def err_grant_expired(msg="Share grant is expired or revoked"):
    return ApiError("ERR_GRANT_EXPIRED", 410, msg)


def err_segregation_of_duties(msg="Approver must differ from the submitting technician"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_no_active_policy(msg="Agency has no ACTIVE policy"):
    return ApiError("ERR_NO_ACTIVE_POLICY", 409, msg)
