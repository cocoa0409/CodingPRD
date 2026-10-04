"""Error catalogue (SCAFFOLD errors table / PRD section 5) and the API exception."""

ERR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_PARENT_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_REFERENCE_SCOPE_MISMATCH": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_CAMPAIGN_NOT_ACTIVE": 409,
    "ERR_HOST_SITE_NOT_PERMITTED": 409,
    "ERR_LOCATION_NOT_ACTIVE": 409,
    "ERR_SCREENING_NOT_CLEARED": 409,
    "ERR_RINGER_INACTIVE": 409,
    "ERR_INTAKE_WINDOW_CLOSED": 409,
    "ERR_OUTSIDE_INTAKE_WINDOW": 409,
    "ERR_SHIFT_TOO_LONG": 422,
    "ERR_RINGER_REST_BUFFER_VIOLATION": 409,
    "ERR_MINOR_CURFEW_VIOLATION": 422,
    "ERR_CANTEEN_UNAVAILABLE": 409,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_PLACEMENT_WINDOW_OUTSIDE_PERMISSION": 422,
    "ERR_EXCLUSIVITY_CONFLICT": 409,
    "ERR_KETTLE_CAP_EXCEEDED": 409,
    "ERR_DUPLICATE_LOCATION_CODE": 409,
    "ERR_DUPLICATE_EXTERNAL_REF": 409,
    "ERR_PROGRAM_INTAKE_FULL": 409,
    "ERR_HOUSEHOLD_SIZE_INVALID": 422,
    "ERR_PROGRAM_AT_CAPACITY": 409,
    "ERR_GIVING_OUTSIDE_CAMPAIGN_WINDOW": 422,
    "ERR_COLLECTION_OUTSIDE_PLACEMENT_WINDOW": 422,
    "ERR_DISTRIBUTION_SLOT_CONFLICT": 409,
    "ERR_REALLOCATION_WINDOW_INVALID": 422,
    "ERR_VARIANCE_EXCEEDS_TOLERANCE": 409,
    "ERR_DEPOSIT_AMOUNT_MISMATCH": 422,
    "ERR_LABOR_BUDGET_EXCEEDED": 409,
    "ERR_INVALID_GIFT_AMOUNT": 422,
    "ERR_REALLOCATION_HOURS_EXCEED_SOURCE": 409,
    "ERR_HOUSEHOLD_LIMIT_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_LOCATION": 422,
    "ERR_NO_ELIGIBLE_RINGER": 422,
    "ERR_STALE_VERSION": 412,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-Role and X-User-ID headers are required and must name a known role.",
    "ERR_FORBIDDEN": "The authenticated role is not authorized for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting identity is not the owner of the addressed resource.",
    "ERR_INVALID_REQUEST": "The request body is malformed or missing a required input.",
    "ERR_RESOURCE_NOT_FOUND": "The resource addressed by the path id does not exist.",
    "ERR_PARENT_NOT_FOUND": "A parent resource named in the path does not exist.",
    "ERR_REFERENCE_NOT_FOUND": "A body foreign key does not resolve to an existing row.",
    "ERR_REFERENCE_SCOPE_MISMATCH": "A body foreign key belongs to a different campaign or unit scope.",
    "ERR_INVALID_STATE_TRANSITION": "The target resource is not in a state that permits this operation.",
    "ERR_ALREADY_TERMINAL": "The target resource is already in a terminal state.",
    "ERR_CAMPAIGN_NOT_ACTIVE": "The owning campaign is not ACTIVE.",
    "ERR_HOST_SITE_NOT_PERMITTED": "The host site permission is not APPROVED.",
    "ERR_LOCATION_NOT_ACTIVE": "The kettle location is not ACTIVE.",
    "ERR_SCREENING_NOT_CLEARED": "The bell ringer's screening is not CLEARED for this shift start.",
    "ERR_RINGER_INACTIVE": "The bell ringer's engagement status is not ACTIVE.",
    "ERR_INTAKE_WINDOW_CLOSED": "The assistance program is not OPEN for intake.",
    "ERR_OUTSIDE_INTAKE_WINDOW": "The logical clock is outside the program intake window.",
    "ERR_SHIFT_TOO_LONG": "The shift duration exceeds 480 minutes.",
    "ERR_RINGER_REST_BUFFER_VIOLATION": "Less than 30 minutes separates this shift from an adjacent shift.",
    "ERR_MINOR_CURFEW_VIOLATION": "A ringer under 18 may not be scheduled past the 20:00 curfew.",
    "ERR_CANTEEN_UNAVAILABLE": "The requested canteens exceed the unit's uncommitted pool.",
    "ERR_SHIFT_OVERLAP": "The requested interval overlaps another live shift for the same ringer.",
    "ERR_PLACEMENT_WINDOW_OUTSIDE_PERMISSION": "The placement window is not contained in the permission window.",
    "ERR_EXCLUSIVITY_CONFLICT": "An exclusive host site already carries an overlapping or touching placement.",
    "ERR_KETTLE_CAP_EXCEEDED": "Activating the location would exceed the host site's max_kettles.",
    "ERR_DUPLICATE_LOCATION_CODE": "location_code is already used within this campaign.",
    "ERR_DUPLICATE_EXTERNAL_REF": "external_ref is already used within this campaign.",
    "ERR_PROGRAM_INTAKE_FULL": "The program has reached its household cap.",
    "ERR_HOUSEHOLD_SIZE_INVALID": "household_size must be between 1 and 12 inclusive.",
    "ERR_PROGRAM_AT_CAPACITY": "The corps program is at capacity and waitlisting is disabled.",
    "ERR_GIVING_OUTSIDE_CAMPAIGN_WINDOW": "occurred_at falls outside the campaign window.",
    "ERR_COLLECTION_OUTSIDE_PLACEMENT_WINDOW": "collected_on falls outside the placement window.",
    "ERR_DISTRIBUTION_SLOT_CONFLICT": "The appointment overlaps another appointment at the same unit.",
    "ERR_REALLOCATION_WINDOW_INVALID": "effective_on is outside the campaign window or precedes the clock.",
    "ERR_VARIANCE_EXCEEDS_TOLERANCE": "The bank-confirmed amount differs by more than 500 cents.",
    "ERR_DEPOSIT_AMOUNT_MISMATCH": "The deposit does not equal counted total minus handling fee.",
    "ERR_LABOR_BUDGET_EXCEEDED": "Completing the shift would exceed the campaign labor budget.",
    "ERR_INVALID_GIFT_AMOUNT": "amount_cents must be greater than 0 and at most 500000.",
    "ERR_REALLOCATION_HOURS_EXCEED_SOURCE": "moved_hours exceeds the source's remaining scheduled hours.",
    "ERR_HOUSEHOLD_LIMIT_EXCEEDED": "The household assistance value exceeds the program limit.",
    "ERR_NO_ELIGIBLE_LOCATION": "No ACTIVE kettle location with an approved host site is available.",
    "ERR_NO_ELIGIBLE_RINGER": "No bell ringer satisfies the screening, engagement, rest and overlap checks.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the parent entity's current version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERR_STATUS.get(error_id, 400)
        super().__init__(self.message)

    def body(self):
        return {"error_id": self.error_id, "message": self.message}


def fail(error_id, message=None):
    raise ApiError(error_id, message)
