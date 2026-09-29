"""Error catalogue (PRD section 5) -- 54 error identifiers."""

ERROR_STATUS = {
    # --- auth / authorisation -------------------------------------------
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape --------------------------------------------------
    "ERR_INVALID_REQUEST": 400,
    # --- existence ------------------------------------------------------
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_OFFICER_NOT_FOUND": 404,
    "ERR_RESIDENT_NOT_FOUND": 404,
    "ERR_DEVICE_NOT_FOUND": 404,
    "ERR_REQUEST_AREA_NOT_FOUND": 404,
    "ERR_VIDEO_REQUEST_NOT_FOUND": 404,
    "ERR_SOLICITATION_NOT_FOUND": 404,
    "ERR_SHARED_CLIP_NOT_FOUND": 404,
    "ERR_POST_NOT_FOUND": 404,
    "ERR_MODERATION_CASE_NOT_FOUND": 404,
    "ERR_TRANSPARENCY_REPORT_NOT_FOUND": 404,
    # --- state / business conflicts -------------------------------------
    "ERR_RESIDENT_DEACTIVATED": 409,
    "ERR_AGENCY_NOT_ONBOARDED": 409,
    "ERR_AGENCY_STATUS_TRANSITION_INVALID": 409,
    "ERR_AREA_ALREADY_LOCKED": 409,
    "ERR_AREA_NOT_LOCKED": 409,
    "ERR_AREA_INVALIDATED": 409,
    "ERR_REQUEST_NOT_IN_DRAFT": 409,
    "ERR_REQUEST_NOT_SOLICITING": 409,
    "ERR_JUSTIFICATION_NOT_LOGGED": 409,
    "ERR_AUDIT_NOT_PENDING": 409,
    "ERR_SOLICITATION_ALREADY_RESOLVED": 409,
    "ERR_DEVICE_DECOMMISSIONED": 409,
    "ERR_CLIP_ALREADY_PURGED": 409,
    "ERR_CLIP_UNDER_LEGAL_HOLD": 409,
    "ERR_POST_NOT_PUBLISHED": 409,
    "ERR_POST_NOT_FLAGGED": 409,
    "ERR_CASE_ALREADY_DECIDED": 409,
    "ERR_POST_NOT_REVISABLE": 409,
    "ERR_REPORT_ALREADY_CERTIFIED": 409,
    "ERR_RESIDENT_OPTED_OUT": 409,
    "ERR_POSTING_SUSPENDED": 409,
    "ERR_DATA_CONTROL_BLOCKED_BY_HOLD": 409,
    "ERR_SOLICITATION_DEADLINE_PASSED": 409,
    "ERR_AREA_CANVASS_OVERLAP": 409,
    "ERR_MIN_DEVICE_THRESHOLD_NOT_MET": 409,
    "ERR_DEVICE_WINDOW_CONFLICT": 409,
    "ERR_SELF_FLAG_NOT_ALLOWED": 409,
    "ERR_DUPLICATE_FLAG": 409,
    "ERR_DUPLICATE_DEVICE_LOCATION": 409,
    "ERR_AGENCY_OPEN_REQUEST_QUOTA_EXCEEDED": 409,
    "ERR_AGENCY_PERIOD_QUOTA_EXCEEDED": 409,
    # --- optimistic concurrency ----------------------------------------
    "ERR_STALE_AREA_VERSION": 412,
    "ERR_STALE_POST_VERSION": 412,
    "ERR_STALE_AGENCY_VERSION": 412,
    # --- semantic (unprocessable) --------------------------------------
    "ERR_JUSTIFICATION_TOO_SHORT": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_CLIP_OUTSIDE_REQUEST_WINDOW": 422,
    "ERR_AREA_RADIUS_EXCEEDS_LIMIT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize()


def fail(error_id, message=None):
    raise ApiError(error_id, message)
