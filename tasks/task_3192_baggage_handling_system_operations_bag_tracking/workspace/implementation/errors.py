"""Error identifiers, messages, HTTP statuses and the API exception type."""

# error_id -> (http_status, human readable message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are missing or the role is not a declared role."),
    "ERR_FORBIDDEN_ROLE": (403, "The acting role may not perform this operation on this resource."),
    "ERR_BAG_NOT_FOUND": (404, "No bag exists for the supplied identifier."),
    "ERR_REPORT_NOT_FOUND": (404, "No mishandled report exists for the supplied identifier."),
    "ERR_FLIGHT_NOT_FOUND": (404, "No flight exists for the supplied identifier."),
    # The system publishes three existence error identifiers, but a station
    # envelope opened by an administrator is equally a resource whose path
    # identifier must resolve; an unallocated id is a not-found, never a
    # malformed request.
    "ERR_STATION_NOT_FOUND": (404, "No station exists for the supplied identifier."),
    "ERR_INVALID_STATE": (409, "The target resource is not in a state that admits the requested transition."),
    "ERR_STALE_VERSION": (412, "The supplied version token does not match the current version of the resource."),
    "ERR_STATION_SUSPENDED": (409, "The station of custody is suspended; the write is refused."),
    "ERR_SCREENING_NOT_CLEARED": (409, "The bag's screening clearance is unresolved."),
    "ERR_SCREENING_EVENT_NOT_ALARMED": (409, "The screening event is not in status ALARMED."),
    "ERR_SCREENING_WINDOW_CLOSED": (409, "The screening window has already closed."),
    "ERR_LANE_OFFLINE": (409, "The screening lane is offline."),
    "ERR_LANE_INTERVAL_CONFLICT": (409, "The lane already hosts a screening window in that identity bucket."),
    "ERR_BAG_OVERWEIGHT": (422, "The declared weight exceeds the carrier's envelope."),
    "ERR_BAG_OVERSIZE": (422, "The declared size exceeds the in-line envelope."),
    "ERR_INTERLINE_AGREEMENT_INACTIVE": (422, "The carrier's interline agreement is not active."),
    "ERR_DUPLICATE_AIRLINE": (409, "An airline with that code already exists."),
    "ERR_DUPLICATE_CONNECTION": (409, "A connection already exists for that bag and onward flight."),
    "ERR_DUPLICATE_BAG_ON_FLIGHT": (409, "The bag is flagged a duplicate for this flight and may not be loaded."),
    "ERR_SORTATION_WINDOW_CLOSED": (409, "The flight's sortation window has closed."),
    "ERR_SORTATION_WINDOW_OPEN": (409, "The flight's sortation window is still open."),
    "ERR_FLIGHT_NOT_SORTING": (409, "The flight is not open for sortation."),
    "ERR_FLIGHT_NOT_ASSIGNED": (409, "The bag has no flight assigned."),
    "ERR_FLIGHT_NOT_DEPARTED": (409, "The bag's flight has not departed."),
    "ERR_MAKEUP_SLOT_CONFLICT": (409, "The claimed make-up interval collides with the area's occupied buckets."),
    "ERR_MAKEUP_AREA_CLOSED": (409, "The make-up area is closed."),
    "ERR_MAKEUP_RATE_LIMITED": (409, "The manual-class load allowance is exhausted for this outage."),
    "ERR_MANUAL_INSPECTION_REQUIRED": (409, "The bag has an open manual inspection task."),
    "ERR_MCT_VIOLATION": (409, "The connection does not satisfy the minimum connect time."),
    "ERR_RUSH_WINDOW_PASSED": (409, "The rush-bag procedure can no longer be declared."),
    "ERR_CONNECTION_MISSED": (409, "The bag's connection has been marked missed."),
    "ERR_CLAIM_NOT_APPROVED": (409, "The report's claim is not approved."),
    "ERR_CLAIM_PENDING": (409, "The report carries a filed but undecided claim."),
    "ERR_CLAIM_ALREADY_DECIDED": (409, "The claim has already been decided."),
    "ERR_COMPENSATION_OVER_CAP": (422, "The requested amount exceeds the carrier's compensation cap."),
    "ERR_COMPENSATION_ALREADY_PAID": (409, "Compensation has already been paid on this report."),
    "ERR_DELIVERY_IN_PAST": (422, "The promised delivery instant precedes the current logical clock instant."),
    "ERR_PROOF_OF_DELIVERY_REQUIRED": (409, "A signed proof of delivery is required."),
    "ERR_OUTAGE_NOT_ACTIVE": (409, "Re-induction is not permitted in the bag's current condition."),
    "ERR_INVALID_REQUEST": (400, "The request body is malformed or a required field is missing or invalid."),
    "ERR_INVALID_ENUM_VALUE": (400, "A supplied enum member is outside the field's declared value set."),
}


class ApiError(Exception):
    def __init__(self, error_id):
        super().__init__(error_id)
        self.error_id = error_id
        status, message = ERRORS.get(error_id, (400, "Request could not be processed."))
        self.http_status = status
        self.message = message


def fail(error_id):
    raise ApiError(error_id)