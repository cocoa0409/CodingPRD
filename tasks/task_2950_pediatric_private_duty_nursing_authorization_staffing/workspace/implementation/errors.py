"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADER": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_PAYER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PAYER_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PLAN_OF_CARE_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_NURSE_NOT_FOUND": 404,
    "ERR_COMPETENCY_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_TIMESHEET_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_STALE_PLAN_OF_CARE_VERSION": 412,
    "ERR_STALE_SHIFT_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_CASE_ON_HOLD": 409,
    "ERR_AUTHORIZATION_NOT_ACTIVE": 409,
    "ERR_PATIENT_HOSPITALIZED": 409,
    "ERR_EVV_NOT_VERIFIED": 409,
    "ERR_TIMESHEET_ALREADY_BILLED": 409,
    "ERR_REDUCTION_NOT_EFFECTIVE": 409,
    "ERR_DISPUTE_ALREADY_OPEN": 409,
    "ERR_SUPERVISORY_VISIT_OVERDUE": 409,
    "ERR_NURSE_SHIFT_OVERLAP": 409,
    "ERR_PATIENT_CONCURRENCY_EXCEEDED": 409,
    "ERR_LICENSE_NUMBER_TAKEN": 409,
    "ERR_COMPETENCY_DUPLICATE": 409,
    "ERR_NURSE_SKILL_MISMATCH": 422,
    "ERR_COMPETENCY_EXPIRED": 422,
    "ERR_NURSE_LICENSE_EXPIRED": 422,
    "ERR_NURSE_NOT_ACTIVE": 422,
    "ERR_NURSE_EXCLUDED_FROM_CASE": 422,
    "ERR_NO_PARENT_BACKUP": 422,
    "ERR_SHIFT_OUTSIDE_AUTH_WINDOW": 422,
    "ERR_CLOCK_IN_TOO_EARLY": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_WEEKLY_HOURS_EXCEEDED": 422,
    "ERR_NURSE_WEEKLY_LIMIT_EXCEEDED": 422,
    "ERR_PAYER_HOUR_CAP_EXCEEDED": 422,
    "ERR_APPROVED_EXCEEDS_REQUESTED": 422,
    "ERR_RENEWAL_UTILIZATION_TOO_LOW": 422,
    "ERR_DECIDED_HOURS_OUT_OF_RANGE": 422,
    "ERR_NO_ELIGIBLE_NURSE": 422,
    "ERR_PAYER_MISMATCH": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)
