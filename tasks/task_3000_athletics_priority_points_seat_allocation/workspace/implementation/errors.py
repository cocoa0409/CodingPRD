"""Error catalogue and the ApiError exception (PRD section 5)."""


class ApiError(Exception):
    """Carries the machine readable error_id, a message and the HTTP status."""

    def __init__(self, error_id, message="", http_status=400):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Complete error catalogue: error_id -> HTTP status (PRD section 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DONOR_NOT_FOUND": 404,
    "ERR_GIFT_NOT_FOUND": 404,
    "ERR_RECALCULATION_NOT_FOUND": 404,
    "ERR_LEDGER_ENTRY_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_SEAT_NOT_FOUND": 404,
    "ERR_SEAT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SELECTION_EVENT_NOT_FOUND": 404,
    "ERR_SELECTION_SLOT_NOT_FOUND": 404,
    "ERR_RELOCATION_REQUEST_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_REFERENCED_ENTITY_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_RECALCULATION_NOT_CERTIFIED": 409,
    "ERR_SECTION_UNDER_RENOVATION": 409,
    "ERR_EVENT_SLOTS_STALE": 409,
    "ERR_EVENT_NOT_OPEN_FOR_REQUESTS": 409,
    "ERR_TRANSFER_POLICY_EXCEPTION_REQUIRED": 422,
    "ERR_OUTSIDE_SLOT_WINDOW": 422,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_SELECTION_WINDOW_OVERLAP": 409,
    "ERR_SEAT_NOT_AVAILABLE": 409,
    "ERR_SEAT_HOLD_CONFLICT": 409,
    "ERR_INFO_REQUEST_LIMIT_REACHED": 422,
    "ERR_NO_ELIGIBLE_DONORS": 422,
    "ERR_SLOT_WINDOW_OVERFLOW": 422,
    "ERR_HOUSEHOLD_LINK_INVALID": 409,
    "ERR_RELOCATION_TARGET_INVALID": 422,
    "ERR_SEAT_POINTS_SHORTFALL": 422,
    "ERR_SEAT_DONATION_SHORTFALL": 402,
    "ERR_TRANSFER_AMOUNT_EXCEEDS_BALANCE": 422,
    "ERR_SECTION_CAPACITY_EXCEEDED": 409,
}


def err(error_id, message=""):
    """Build an ApiError whose HTTP status comes from the catalogue."""
    return ApiError(error_id, message, ERROR_STATUS.get(error_id, 400))


def raise_err(error_id, message=""):
    raise err(error_id, message)


# Convenience shorthands used across the route modules -----------------------
def invalid(message="malformed request"):
    return err("ERR_INVALID_REQUEST", message)


def invalid_state(message="the resource's current state does not admit this transition"):
    return err("ERR_INVALID_STATE", message)


def stale(message="the supplied version stamp does not match the parent's current version"):
    return err("ERR_STALE_VERSION", message)


def referenced_missing(message="an id supplied in the request body does not resolve"):
    return err("ERR_REFERENCED_ENTITY_NOT_FOUND", message)
