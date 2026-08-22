"""Error catalogue (PRD section 5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


# id -> HTTP status
CATALOG = {
    # auth / shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    # existence
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_CONCERT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_MUSICIAN_NOT_FOUND": 404,
    "ERR_SERVICE_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_PATRON_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_TICKET_ORDER_NOT_FOUND": 404,
    "ERR_AD_BOOKING_NOT_FOUND": 404,
    # season / concert state
    "ERR_INVALID_SEASON_TRANSITION": 409,
    "ERR_UNION_AGREEMENT_MISSING": 409,
    "ERR_UNION_AGREEMENT_DUPLICATE": 409,
    "ERR_NO_PROGRAMMED_CONCERTS": 409,
    "ERR_CONCERT_NOT_DRAFT": 409,
    "ERR_CONCERT_NOT_PROGRAMMED": 409,
    "ERR_CONCERT_NOT_ON_SALE": 409,
    "ERR_CONCERT_ALREADY_CANCELLED": 409,
    "ERR_CONCERT_NOT_SETTLEABLE": 409,
    # contract / service / engagement state
    "ERR_CONTRACT_NOT_NEGOTIABLE": 409,
    "ERR_SERVICE_NOT_DRAFT": 409,
    "ERR_SERVICE_NOT_PUBLISHED": 409,
    "ERR_ENGAGEMENT_NOT_CONFIRMED": 409,
    # subscription / ticket / ad state
    "ERR_SUBSCRIPTION_NOT_PENDING": 409,
    "ERR_SUBSCRIPTION_NOT_ACTIVE": 409,
    "ERR_TICKET_ORDER_NOT_HELD": 409,
    "ERR_AD_BOOKING_NOT_SUBMITTED": 409,
    "ERR_RENEWAL_WINDOW_CLOSED": 409,
    "ERR_RENEWAL_DEADLINE_PASSED": 409,
    # optimistic concurrency
    "ERR_STALE_CONCERT_VERSION": 412,
    "ERR_STALE_PACKAGE_VERSION": 412,
    # union safety
    "ERR_UNION_BREAK_VIOLATION": 422,
    "ERR_UNION_REST_VIOLATION": 422,
    "ERR_UNION_DAILY_SERVICE_CAP": 409,
    "ERR_DOUBLING_LIMIT_EXCEEDED": 422,
    # temporal / capacity / benefit
    "ERR_VENUE_CHANGEOVER_CONFLICT": 409,
    "ERR_INSUFFICIENT_COMPLEMENT": 409,
    "ERR_NEGOTIATION_ROUND_LIMIT": 422,
    "ERR_DONOR_BENEFIT_REQUIRED": 422,
    "ERR_RENEWAL_PRIORITY_INSUFFICIENT": 422,
    "ERR_PACKAGE_CONCERT_MISMATCH": 422,
    "ERR_SEAT_SECTION_VENUE_MISMATCH": 422,
    "ERR_INSUFFICIENT_SEATS": 409,
}

_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and a valid X-User-Role header are required.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own this resource.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_SEASON_NOT_FOUND": "Season not found.",
    "ERR_VENUE_NOT_FOUND": "Venue not found.",
    "ERR_SECTION_NOT_FOUND": "Seat section not found.",
    "ERR_CONCERT_NOT_FOUND": "Concert not found.",
    "ERR_CONTRACT_NOT_FOUND": "Guest artist contract not found.",
    "ERR_MUSICIAN_NOT_FOUND": "Musician not found.",
    "ERR_SERVICE_NOT_FOUND": "Rehearsal service not found.",
    "ERR_ENGAGEMENT_NOT_FOUND": "Musician engagement not found.",
    "ERR_PATRON_NOT_FOUND": "Patron not found.",
    "ERR_SUBSCRIPTION_NOT_FOUND": "Subscription package not found.",
    "ERR_TICKET_ORDER_NOT_FOUND": "Ticket order not found.",
    "ERR_AD_BOOKING_NOT_FOUND": "Ad booking not found.",
}


def err(error_id, message=None):
    return ApiError(error_id, CATALOG[error_id], message)


def raise_err(error_id, message=None):
    raise err(error_id, message)
