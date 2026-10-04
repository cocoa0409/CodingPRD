class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def unauthorized(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def forbidden(msg="Entity-backed X-User-ID does not own the target resource"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def not_found(msg="Referenced id does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def invalid_request(msg="Required field missing, wrong type, or malformed value"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def validation(msg="Structural constraint violated"):
    return ApiError("ERR_VALIDATION", msg, 400)


def cross_reference(msg="Cross-reference mismatch"):
    return ApiError("ERR_CROSS_REFERENCE_MISMATCH", msg, 422)


def invalid_state(msg="Resource not in valid from-state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def stale_version(msg="expected version mismatch"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def active_question_set_exists(msg="Another question set is already ACTIVE"):
    return ApiError("ERR_ACTIVE_QUESTION_SET_EXISTS", msg, 409)


def question_set_not_active(msg="Pinned question set is not ACTIVE"):
    return ApiError("ERR_QUESTION_SET_NOT_ACTIVE", msg, 409)


def wave_not_open(msg="Wave is not OPEN"):
    return ApiError("ERR_WAVE_NOT_OPEN", msg, 409)


def wave_still_open(msg="Logical clock has not reached period_end"):
    return ApiError("ERR_WAVE_STILL_OPEN", msg, 422)


def response_window_closed(msg="Response window has closed"):
    return ApiError("ERR_RESPONSE_WINDOW_CLOSED", msg, 422)


def contact_restricted(msg="Customer do_not_contact is true"):
    return ApiError("ERR_CONTACT_RESTRICTED", msg, 422)


def appeal_already_open(msg="An open appeal already exists on this response"):
    return ApiError("ERR_APPEAL_ALREADY_OPEN", msg, 409)


def appeals_pending(msg="Wave finalize blocked by open appeals"):
    return ApiError("ERR_APPEALS_PENDING", msg, 409)


def flags_pending(msg="Wave finalize blocked by unresolved manipulation flags"):
    return ApiError("ERR_FLAGS_PENDING", msg, 409)


def dealer_suspended(msg="SUSPENDED dealer cannot submit a plan"):
    return ApiError("ERR_DEALER_SUSPENDED", msg, 422)
