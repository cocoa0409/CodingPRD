"""Error catalogue (PRD 5). Every identifier maps to exactly one HTTP status."""


ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_AGENCY_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_PAGINATION_INVALID": 400,
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_VOUCHER_NOT_FOUND": 404,
    "ERR_DONATION_OFFER_NOT_FOUND": 404,
    "ERR_INVENTORY_ITEM_NOT_FOUND": 404,
    "ERR_TRUCK_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_STOP_NOT_FOUND": 404,
    "ERR_VOLUNTEER_NOT_FOUND": 404,
    "ERR_CREW_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_SUBMITTED": 409,
    "ERR_REFERRAL_NOT_APPROVED": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_OFFER_INVALID_STATE": 409,
    "ERR_VOUCHER_INVALID_STATE": 409,
    "ERR_FEE_STATE_INVALID": 409,
    "ERR_RUN_INVALID_STATE": 409,
    "ERR_STOP_INVALID_STATE": 409,
    "ERR_CREW_ASSIGNMENT_INVALID_STATE": 409,
    "ERR_QUARANTINE_NOT_ELAPSED": 409,
    "ERR_CLIENT_BED_BUG_BLOCK": 422,
    "ERR_CLIENT_DELIVERY_BANNED": 422,
    "ERR_TRUCK_BED_BUG_LOCKOUT": 409,
    "ERR_REFERRAL_EXPIRED": 409,
    "ERR_TRUCK_WINDOW_CONFLICT": 409,
    "ERR_VOLUNTEER_WINDOW_CONFLICT": 409,
    "ERR_VOUCHER_ALREADY_EXISTS": 409,
    "ERR_DUPLICATE_CREW_ASSIGNMENT": 409,
    "ERR_STOP_SEQUENCE_CONFLICT": 409,
    "ERR_VOUCHER_UNDERFILLED": 422,
    "ERR_DRIVER_NOT_CERTIFIED": 422,
    "ERR_TRUCK_CAPACITY_EXCEEDED": 422,
    "ERR_CREW_BELOW_MINIMUM": 409,
    "ERR_AGENCY_SUSPENDED": 409,
    "ERR_AGENCY_QUOTA_EXHAUSTED": 409,
    "ERR_FEE_AMOUNT_MISMATCH": 422,
    "ERR_STALE_VOUCHER_VERSION": 412,
    "ERR_STALE_RUN_VERSION": 412,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_AGENCY_SCOPE_VIOLATION": "The acting user may not touch this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Quarantine release must be performed by a different warehouse lead.",
    "ERR_VALIDATION": "The request body failed schema validation.",
    "ERR_PAGINATION_INVALID": "limit must be an integer in [1,100] and offset an integer >= 0.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the app handler."""

    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
