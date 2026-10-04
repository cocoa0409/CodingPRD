"""Error catalogue and the ApiError carrier."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_FK_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_AUDIT_NOT_REVIEWED": 409,
    "ERR_COURSE_AUDIT_NOT_APPROVED": 422,
    "ERR_ORDER_WINDOW_CLOSED": 422,
    "ERR_MAX_EXAMS_EXCEEDED": 422,
    "ERR_ORDER_MIN_SIZE": 422,
    "ERR_ORDER_CAPACITY": 422,
    "ERR_SEAL_VERIFICATION_FAILED": 409,
    "ERR_CUSTODY_CHAIN_GAP": 409,
    "ERR_READER_RELIABILITY_BELOW_FLOOR": 409,
    "ERR_NO_ELIGIBLE_READER": 409,
    "ERR_RELEASE_BLOCKED": 409,
    "ERR_SCORE_RELEASE_TOO_EARLY": 422,
    "ERR_CANCELLATION_DEADLINE_PASSED": 422,
    "ERR_ALT_SEAT_CONFLICT": 409,
    "ERR_DOCUMENTS_INCOMPLETE": 422,
    "ERR_LATE_FEE_UNPAID": 402,
    "ERR_SEND_FEE_UNPAID": 402,
    "ERR_DESIGNATION_SLOTS_EXHAUSTED": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SYLLABUS_UNCHANGED": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_NO_ALTERNATE_FORM": 409,
    "ERR_ACCOMMODATION_PROVISION_INCOMPLETE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unknown identity headers.",
    "ERR_UNAUTHORIZED": "The acting role may not call this endpoint.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user submitted or reported the record under review.",
    "ERR_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_FK_NOT_FOUND": "A referenced foreign key does not resolve to an existing row.",
    "ERR_INVALID_STATE": "The entity's current status does not admit the requested transition.",
    "ERR_ALREADY_TERMINAL": "The entity already sits in a terminal state.",
    "ERR_AUDIT_NOT_REVIEWED": "The course audit has not completed a review pass.",
    "ERR_COURSE_AUDIT_NOT_APPROVED": "The course audit is not approved or the school holds no program-label authorization.",
    "ERR_ORDER_WINDOW_CLOSED": "The ordering window at the logical clock is not open.",
    "ERR_MAX_EXAMS_EXCEEDED": "The student already holds the maximum number of registrations for the year.",
    "ERR_ORDER_MIN_SIZE": "The order holds fewer registrations than the minimum order size.",
    "ERR_ORDER_CAPACITY": "The order would exceed the maximum number of examinees.",
    "ERR_SEAL_VERIFICATION_FAILED": "The seal was not intact where the school requires one.",
    "ERR_CUSTODY_CHAIN_GAP": "The custody chain is not gap-free.",
    "ERR_READER_RELIABILITY_BELOW_FLOOR": "The reader's reliability index is below the floor.",
    "ERR_NO_ELIGIBLE_READER": "No eligible reader is available for this exam subject.",
    "ERR_RELEASE_BLOCKED": "An open irregularity case blocks this score operation.",
    "ERR_SCORE_RELEASE_TOO_EARLY": "The score release instant has not arrived.",
    "ERR_CANCELLATION_DEADLINE_PASSED": "The cancellation and withholding deadline has passed.",
    "ERR_ALT_SEAT_CONFLICT": "The alternate administration collides with an existing block.",
    "ERR_DOCUMENTS_INCOMPLETE": "The documentation is below the completeness threshold.",
    "ERR_LATE_FEE_UNPAID": "The assessed late fee has not been settled.",
    "ERR_SEND_FEE_UNPAID": "The score-send fee has not been settled.",
    "ERR_DESIGNATION_SLOTS_EXHAUSTED": "The school's designation slot budget is exhausted.",
    "ERR_STALE_VERSION": "The supplied version does not match the entity's current version.",
    "ERR_DUPLICATE_RESOURCE": "A uniquely constrained field already exists.",
    "ERR_INVALID_REQUEST": "The request shape is invalid.",
    "ERR_SYLLABUS_UNCHANGED": "The submitted syllabus hash is identical to the previous submission.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window has closed.",
    "ERR_NO_ALTERNATE_FORM": "The form code does not resolve to an available alternate form.",
    "ERR_ACCOMMODATION_PROVISION_INCOMPLETE": "The approved accommodation provision has not been recorded.",
}


class ApiError(Exception):
    """Carries an error_id, an HTTP status and a human-readable message."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


def fail(error_id, message=None, http_status=None):
    raise ApiError(error_id, message, http_status)
