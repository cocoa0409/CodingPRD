"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PRODUCER_NOT_FOUND": 404,
    "ERR_TRAINING_COURSE_NOT_FOUND": 404,
    "ERR_COURSE_ENROLLMENT_NOT_FOUND": 404,
    "ERR_SERIES_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_ATTESTATION_NOT_FOUND": 404,
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_PLAYBACK_SLOT_NOT_FOUND": 404,
    "ERR_STUDIO_RESOURCE_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_DAMAGE_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CREW_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_FUNDING_PERIOD_NOT_FOUND": 404,
    "ERR_ARCHIVE_ASSET_NOT_FOUND": 404,
    "ERR_STALE_SERIES_VERSION": 412,
    "ERR_STALE_FUNDING_PERIOD_VERSION": 412,
    "ERR_PRODUCER_NOT_ACTIVE": 409,
    "ERR_PROGRAM_NOT_APPROVED": 409,
    "ERR_ATTESTATION_INCOMPLETE": 409,
    "ERR_SERIES_NOT_ACTIVE": 409,
    "ERR_RESOURCE_NOT_AVAILABLE": 409,
    "ERR_COMPETENCY_NOT_HELD": 422,
    "ERR_CERTIFICATION_INSUFFICIENT": 422,
    "ERR_PREREQUISITE_NOT_MET": 422,
    "ERR_COURSE_FULL": 409,
    "ERR_SLOT_UNDERSTAFFED": 409,
    "ERR_RESOURCE_HAS_OPEN_RESERVATIONS": 409,
    "ERR_FINDING_CATEGORY_NOT_PERMITTED": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_COURSE_SESSION_NOT_ENDED": 409,
    "ERR_WITHDRAWAL_WINDOW_CLOSED": 409,
    "ERR_INDEMNIFICATION_EXPIRED": 422,
    "ERR_SLOT_OUTSIDE_CHANNEL_WINDOW": 422,
    "ERR_SLOT_WINDOW_CONFLICT": 409,
    "ERR_SERIES_HOLD_EXHAUSTED": 409,
    "ERR_RESOURCE_OVERBOOKED": 409,
    "ERR_CHECKOUT_WINDOW_NOT_OPEN": 409,
    "ERR_AIRTIME_NOT_REACHED": 409,
    "ERR_RETENTION_NOT_ELAPSED": 409,
    "ERR_PERMANENT_RETENTION": 409,
    "ERR_CREW_TIME_CONFLICT": 409,
    "ERR_SERIES_NOT_OWNED_BY_PRODUCER": 422,
    "ERR_CHANNEL_TIER_NOT_ELIGIBLE": 422,
    "ERR_SLOT_PRODUCER_MISMATCH": 422,
    "ERR_DUPLICATE_ENROLLMENT": 409,
    "ERR_DUPLICATE_NATURAL_KEY": 409,
    "ERR_LICENSE_REFERENCE_REQUIRED": 422,
    "ERR_DEPOSIT_LIMIT_EXCEEDED": 402,
    "ERR_ALLOCABLE_BASE_NOT_POSITIVE": 402,
    "ERR_CAPITAL_GRANT_EXCEEDS_BASE": 402,
}

# entity kind -> not-found error id
NOT_FOUND = {
    "producer": "ERR_PRODUCER_NOT_FOUND",
    "training_course": "ERR_TRAINING_COURSE_NOT_FOUND",
    "course_enrollment": "ERR_COURSE_ENROLLMENT_NOT_FOUND",
    "series": "ERR_SERIES_NOT_FOUND",
    "program": "ERR_PROGRAM_NOT_FOUND",
    "attestation": "ERR_ATTESTATION_NOT_FOUND",
    "channel": "ERR_CHANNEL_NOT_FOUND",
    "playback_slot": "ERR_PLAYBACK_SLOT_NOT_FOUND",
    "studio_resource": "ERR_STUDIO_RESOURCE_NOT_FOUND",
    "reservation": "ERR_RESERVATION_NOT_FOUND",
    "damage_assessment": "ERR_DAMAGE_ASSESSMENT_NOT_FOUND",
    "crew_assignment": "ERR_CREW_ASSIGNMENT_NOT_FOUND",
    "funding_period": "ERR_FUNDING_PERIOD_NOT_FOUND",
    "archive_asset": "ERR_ARCHIVE_ASSET_NOT_FOUND",
}


class ApiError(Exception):
    """Raised anywhere in a request to refuse it with a catalogue identifier."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize()


def bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def not_found(kind, ident=None):
    error_id = NOT_FOUND[kind]
    label = kind.replace("_", " ")
    if ident is None:
        return ApiError(error_id, "%s not found" % label.capitalize())
    return ApiError(error_id, "%s %s not found" % (label.capitalize(), ident))


def invalid_transition(message="Operation is not legal from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)
