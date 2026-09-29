"""Error catalogue (PRD §5) and the ApiError exception.

Exactly 59 identifiers, each with the HTTP status pinned in the PRD table.
"""

ERROR_STATUS = {
    # --- authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- payload shape
    "ERR_VALIDATION": 422,
    "ERR_INVALID_ENUM": 422,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_PAGINATION_INVALID": 422,
    # --- existence
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_HOUSEHOLD_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_NOT_FOUND": 404,
    "ERR_GUEST_VISIT_NOT_FOUND": 404,
    "ERR_LIFEGUARD_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_GUARD_SHIFT_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_MEET_NOT_FOUND": 404,
    "ERR_VOLUNTEER_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PARTY_RESERVATION_NOT_FOUND": 404,
    "ERR_INSPECTION_FINDING_NOT_FOUND": 404,
    "ERR_CONDUCT_CASE_NOT_FOUND": 404,
    "ERR_CAPITAL_PROJECT_NOT_FOUND": 404,
    # --- stale-version guards
    "ERR_STALE_HOUSEHOLD_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    # --- resource state
    "ERR_SEASON_NOT_OPEN": 409,
    "ERR_FACILITY_CLOSED": 409,
    "ERR_FACILITY_RESTRICTED": 409,
    "ERR_INVALID_TRANSITION": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_HOUSEHOLD_SUSPENDED": 409,
    "ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING": 409,
    "ERR_ROSTER_ALREADY_CLOSED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_MAX_DEFERRALS_REACHED": 409,
    # --- safety & compliance
    "ERR_CERT_NOT_VALID_FOR_SHIFT": 422,
    "ERR_GUARD_RATIO_NOT_MET": 422,
    # --- temporal windows
    "ERR_OUTSIDE_SEASON_WINDOW": 422,
    "ERR_VISIT_IN_FUTURE": 422,
    # --- constraint satisfaction
    "ERR_SHIFT_REST_BUFFER_VIOLATION": 409,
    "ERR_ZONE_DOUBLE_BOOKED": 409,
    "ERR_BATHER_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_MEMBERSHIP": 409,
    "ERR_DUPLICATE_WAITLIST_ENTRY": 409,
    "ERR_GUEST_LIMIT_EXCEEDED": 422,
    "ERR_HOUSEHOLD_SIZE_EXCEEDED": 422,
    "ERR_VOLUNTEER_SLOTS_FULL": 409,
    "ERR_DUPLICATE_VOLUNTEER_ASSIGNMENT": 409,
    "ERR_SQUAD_FULL": 409,
    # --- referential agreement
    "ERR_WAITLIST_OFFER_REQUIRED": 409,
    "ERR_CATEGORY_MISMATCH": 422,
    "ERR_SEASON_MISMATCH": 422,
    "ERR_WAITLIST_EMPTY": 409,
    # --- fiscal
    "ERR_DUES_DELINQUENT": 402,
    "ERR_BOND_NOT_PAID": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_INSUFFICIENT_RESERVE": 402,
    "ERR_DRAW_EXCEEDS_BUDGET": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unknown role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting household does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not raise and decide this item.",
    "ERR_VALIDATION": "The request payload is invalid.",
    "ERR_INVALID_ENUM": "An enum-valued input holds a value outside its declared set.",
    "ERR_INVALID_TIME_RANGE": "A start instant or date is not strictly earlier than its paired end.",
    "ERR_PAGINATION_INVALID": "Pagination arguments are invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )


def fail(error_id, message=None):
    raise ApiError(error_id, message)
