"""Error catalogue (PRD section 5) and the API exception type."""

ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_NO_APPOINTMENT_LINES = "ERR_NO_APPOINTMENT_LINES"
ERR_OVERRIDE_ALREADY_PENDING = "ERR_OVERRIDE_ALREADY_PENDING"
ERR_WINDOW_OVERLAP = "ERR_WINDOW_OVERLAP"
ERR_WINDOW_INVALID = "ERR_WINDOW_INVALID"
ERR_VISIT_OVERLAP = "ERR_VISIT_OVERLAP"
ERR_NO_ELIGIBLE_TECHNICIAN = "ERR_NO_ELIGIBLE_TECHNICIAN"
ERR_MEMBER_VISIT_SEQUENCE_INVALID = "ERR_MEMBER_VISIT_SEQUENCE_INVALID"
ERR_PRICEBOOK_REVISION_NOT_PUBLISHED = "ERR_PRICEBOOK_REVISION_NOT_PUBLISHED"
ERR_TECHNICIAN_CAPACITY_EXCEEDED = "ERR_TECHNICIAN_CAPACITY_EXCEEDED"
ERR_DUPLICATE_VISIT_SEQUENCE = "ERR_DUPLICATE_VISIT_SEQUENCE"
ERR_SUBSCRIPTION_TERM_EXCEEDED = "ERR_SUBSCRIPTION_TERM_EXCEEDED"
ERR_OVERRIDE_EXCEEDS_LIMIT = "ERR_OVERRIDE_EXCEEDS_LIMIT"
ERR_DISCOUNT_FLOOR_REACHED = "ERR_DISCOUNT_FLOOR_REACHED"
ERR_OVER_COLLECTION = "ERR_OVER_COLLECTION"
ERR_MEMBERSHIP_CANCEL_BLOCKED = "ERR_MEMBERSHIP_CANCEL_BLOCKED"
ERR_AGREEMENT_NOT_ACTIVE = "ERR_AGREEMENT_NOT_ACTIVE"
ERR_DESCRIPTION_TOO_SHORT = "ERR_DESCRIPTION_TOO_SHORT"
ERR_CALL_NOT_REVIEWABLE = "ERR_CALL_NOT_REVIEWABLE"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

HTTP_STATUS = {
    ERR_UNAUTHORIZED: 401,
    ERR_FORBIDDEN: 403,
    ERR_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_NO_APPOINTMENT_LINES: 409,
    ERR_OVERRIDE_ALREADY_PENDING: 409,
    ERR_WINDOW_OVERLAP: 409,
    ERR_WINDOW_INVALID: 400,
    ERR_VISIT_OVERLAP: 409,
    ERR_NO_ELIGIBLE_TECHNICIAN: 422,
    ERR_MEMBER_VISIT_SEQUENCE_INVALID: 422,
    ERR_PRICEBOOK_REVISION_NOT_PUBLISHED: 422,
    ERR_TECHNICIAN_CAPACITY_EXCEEDED: 422,
    ERR_DUPLICATE_VISIT_SEQUENCE: 409,
    ERR_SUBSCRIPTION_TERM_EXCEEDED: 422,
    ERR_OVERRIDE_EXCEEDS_LIMIT: 422,
    ERR_DISCOUNT_FLOOR_REACHED: 422,
    ERR_OVER_COLLECTION: 422,
    ERR_MEMBERSHIP_CANCEL_BLOCKED: 409,
    ERR_AGREEMENT_NOT_ACTIVE: 409,
    ERR_DESCRIPTION_TOO_SHORT: 422,
    ERR_CALL_NOT_REVIEWABLE: 409,
    ERR_STALE_VERSION: 412,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_INVALID_REQUEST: 400,
}

MESSAGES = {
    ERR_UNAUTHORIZED: "Authentication required: X-User-Role must name a declared role and X-User-ID must be present and non-empty.",
    ERR_FORBIDDEN: "The acting role is not permitted on this endpoint.",
    ERR_NOT_FOUND: "The resource named by a path parameter does not exist.",
    ERR_INVALID_STATE: "The target entity is not in a state from which the requested transition is declared.",
    ERR_NO_APPOINTMENT_LINES: "The appointment carries no AppointmentLine rows and cannot be dispatched.",
    ERR_OVERRIDE_ALREADY_PENDING: "A price override request on this appointment is still pending.",
    ERR_WINDOW_OVERLAP: "The service window overlaps another live appointment on the same branch.",
    ERR_WINDOW_INVALID: "window_end_utc must be strictly later than window_start_utc.",
    ERR_VISIT_OVERLAP: "The maintenance interval overlaps another live visit on the same agreement.",
    ERR_NO_ELIGIBLE_TECHNICIAN: "No candidate technician holds every required skill code of the appointment's published revisions.",
    ERR_MEMBER_VISIT_SEQUENCE_INVALID: "The named membership visit sequence does not exist on the linked agreement or is already completed.",
    ERR_PRICEBOOK_REVISION_NOT_PUBLISHED: "The requested pricebook code has no revision whose status is PUBLISHED.",
    ERR_TECHNICIAN_CAPACITY_EXCEEDED: "The selected technician is already at or above their daily capacity.",
    ERR_DUPLICATE_VISIT_SEQUENCE: "A membership visit with this sequence number already exists on the agreement.",
    ERR_SUBSCRIPTION_TERM_EXCEEDED: "The requested sequence number exceeds the agreement's total visit entitlement.",
    ERR_OVERRIDE_EXCEEDS_LIMIT: "The requested price exceeds the maximum approvable price for this appointment.",
    ERR_DISCOUNT_FLOOR_REACHED: "The appointment's effective discount exceeds the twenty percent sales floor.",
    ERR_OVER_COLLECTION: "The payment would push collected amounts beyond the agreement's annual price.",
    ERR_MEMBERSHIP_CANCEL_BLOCKED: "The agreement has fulfilled visits and the refund formula does not leave an amount strictly below the annual price.",
    ERR_AGREEMENT_NOT_ACTIVE: "The linked membership agreement is neither PENDING_PAYMENT nor ACTIVE.",
    ERR_DESCRIPTION_TOO_SHORT: "The completion description is missing or shorter than the required word count.",
    ERR_CALL_NOT_REVIEWABLE: "The call has no attributed appointment, or the attributed appointment is not COMPLETED.",
    ERR_STALE_VERSION: "The supplied expected version does not match the server's current version.",
    ERR_SEGREGATION_OF_DUTIES: "The acting user both earned and is now voiding the same appointment's creditable revenue.",
    ERR_INVALID_REQUEST: "A required request field is missing or not parseable.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)


def not_found(what="resource"):
    return ApiError(ERR_NOT_FOUND, "The %s named by a path parameter does not exist." % what)


def invalid_state(message=None):
    return ApiError(ERR_INVALID_STATE, message)


def invalid_request(message=None):
    return ApiError(ERR_INVALID_REQUEST, message)