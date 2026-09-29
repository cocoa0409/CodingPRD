"""Error catalogue for the Fair Grandstand Entertainment Booking API (PRD section 5)."""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Missing or invalid authentication headers."),
    "ERR_FORBIDDEN_ROLE": (403, "This role may not perform this operation."),
    "ERR_INVALID_REQUEST": (400, "Request payload failed schema validation."),
    "ERR_UNKNOWN_ACTOR_IDENTITY": (403, "The acting identity is not a registered talent agent."),
    "ERR_FAIR_EDITION_NOT_FOUND": (404, "Fair edition not found."),
    "ERR_STAGE_NOT_FOUND": (404, "Stage not found."),
    "ERR_TALENT_AGENT_NOT_FOUND": (404, "Talent agent not found."),
    "ERR_ARTIST_NOT_FOUND": (404, "Artist not found."),
    "ERR_OFFER_NOT_FOUND": (404, "Offer not found."),
    "ERR_SHOW_BOOKING_NOT_FOUND": (404, "Show booking not found."),
    "ERR_TICKET_SCALE_NOT_FOUND": (404, "Ticket scale not found."),
    "ERR_PRODUCTION_ADVANCE_NOT_FOUND": (404, "Production advance not found."),
    "ERR_RIDER_ITEM_NOT_FOUND": (404, "Rider item not found."),
    "ERR_SPONSOR_NOT_FOUND": (404, "Sponsor not found."),
    "ERR_ACTIVATION_NOT_FOUND": (404, "Sponsorship activation not found."),
    "ERR_SETTLEMENT_NOT_FOUND": (404, "Settlement not found."),
    "ERR_INVALID_OFFER_STATE": (409, "The offer is not in a state that allows this action."),
    "ERR_OFFER_EXPIRED": (409, "The offer response window has closed."),
    "ERR_INVALID_BOOKING_STATE": (409, "The booking's contractual state does not allow this action."),
    "ERR_INVALID_TICKETING_STATE": (409, "The booking's box-office state does not allow this action."),
    "ERR_INVALID_ADVANCE_STATE": (409, "The production advance is not in a state that allows this action."),
    "ERR_INVALID_ACTIVATION_STATE": (409, "The activation is not in a state that allows this action."),
    "ERR_INVALID_SETTLEMENT_STATE": (409, "The settlement is not in a state that allows this action."),
    "ERR_STALE_OFFER_VERSION": (412, "The offer has changed since it was read."),
    "ERR_STALE_SHOW_BOOKING_VERSION": (412, "The show booking has changed since it was read."),
    "ERR_SHOW_DATE_OUTSIDE_FAIR_RUN": (422, "The performance date falls outside the fair run."),
    "ERR_INVALID_SLOT_WINDOW": (422, "The occupation window is malformed."),
    "ERR_REPLACEMENT_DATE_INVALID": (422, "The replacement performance date is invalid."),
    "ERR_SHOW_NOT_YET_CONCLUDED": (422, "The show has not concluded."),
    "ERR_CURFEW_VIOLATION": (422, "The occupation window breaches the municipal curfew."),
    "ERR_ADVANCE_NOT_COMPLETE": (409, "The production advance is not complete."),
    "ERR_ADVANCE_HAS_OPEN_ITEMS": (409, "The production advance still has unruled rider items."),
    "ERR_AGENT_NOT_AUTHORIZED_FOR_ARTIST": (403, "This agent does not represent the artist on the offer."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The submitter of a settlement may not approve it."),
    "ERR_SETTLEMENT_ALREADY_EXISTS": (409, "A settlement already exists for this booking."),
    "ERR_SPONSOR_CATEGORY_EXCLUSIVITY_CONFLICT": (409, "Another sponsor already holds this trade category on the show."),
    "ERR_STAGE_NAMING_ALREADY_GRANTED": (409, "Stage naming rights are already granted for this stage."),
    "ERR_NEGOTIATION_ROUND_LIMIT": (409, "The negotiation round limit has been reached."),
    "ERR_STAGE_SLOT_CONFLICT": (409, "The stage is already occupied in this window."),
    "ERR_RADIUS_CLAUSE_CONFLICT": (409, "The artist's radius clause blocks this date."),
    "ERR_GENRE_ADJACENCY_CONFLICT": (422, "Another show of the same genre is already booked adjacent to this date."),
    "ERR_DAY_SLOT_CAPACITY_EXCEEDED": (409, "The fair's per-day show capacity is exhausted."),
    "ERR_ALLOTMENT_EXCEEDS_STAGE_CAPACITY": (422, "The seat allotment exceeds the stage's capacity for this seating type."),
    "ERR_NO_TICKET_SCALES": (422, "The show has no ticket scales."),
    "ERR_REFUND_EXCEEDS_SOLD_UNITS": (422, "The refund exceeds the units currently sold."),
    "ERR_TALENT_BUDGET_EXCEEDED": (422, "The talent budget cap would be exceeded."),
    "ERR_REFUND_RESERVE_EXCEEDED": (422, "The edition's refund reserve is insufficient."),
    "ERR_SETTLEMENT_NEGATIVE_PAYOUT": (422, "The settlement would owe the artist a negative amount."),
    "ERR_NOT_FOUND": (404, "The requested resource does not exist."),
    "ERR_METHOD_NOT_ALLOWED": (405, "The HTTP method is not allowed for this resource."),
}


class ApiError(Exception):
    """A business/validation failure that maps onto a catalogued error identifier."""

    def __init__(self, error_id, message=None, http_status=None):
        catalog = ERROR_CATALOG.get(error_id, (400, "Request failed."))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else catalog[0]
        self.message = message if message is not None else catalog[1]
        super().__init__("%s: %s" % (error_id, self.message))


def raise_error(error_id, message=None):
    raise ApiError(error_id, message)
