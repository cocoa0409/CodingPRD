"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_ITINERARY_OWNER": 403,
    # existence
    "ERR_TERMINAL_NOT_FOUND": 404,
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_GRANT_NOT_FOUND": 404,
    "ERR_ALLOWANCE_RULE_NOT_FOUND": 404,
    "ERR_STOCK_ITEM_NOT_FOUND": 404,
    "ERR_MOVEMENT_NOT_FOUND": 404,
    "ERR_ITINERARY_NOT_FOUND": 404,
    "ERR_SALE_NOT_FOUND": 404,
    "ERR_SALE_LINE_NOT_FOUND": 404,
    "ERR_SEALED_BAG_NOT_FOUND": 404,
    "ERR_PRE_ORDER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    # well-formedness
    "ERR_INVALID_REQUEST": 422,
    # uniqueness
    "ERR_DUPLICATE_SKU": 409,
    "ERR_DUPLICATE_STOCK_ITEM": 409,
    "ERR_DUPLICATE_BOARDING_PASS": 409,
    "ERR_DUPLICATE_AGREEMENT_PERIOD": 409,
    "ERR_DUPLICATE_SEAL_NUMBER": 409,
    # state
    "ERR_SALE_ALREADY_TERMINAL": 409,
    "ERR_SALE_NOT_IN_CART": 409,
    "ERR_SALE_NOT_CLEARED": 409,
    "ERR_ITINERARY_NOT_SCANNED": 409,
    "ERR_ITINERARY_SCAN_STATE_INVALID": 409,
    "ERR_PRODUCT_NOT_PENDING": 409,
    "ERR_PRODUCT_NOT_LISTED": 409,
    "ERR_GRANT_NOT_ACTIVE": 409,
    "ERR_BRAND_ALREADY_SUSPENDED": 409,
    "ERR_AGREEMENT_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_ALREADY_ACTIVE": 409,
    "ERR_AUDIT_NOT_SUBMITTED": 409,
    "ERR_PREORDER_NOT_RESERVED": 409,
    "ERR_BAG_NOT_ISSUED": 409,
    "ERR_MOVEMENT_NOT_REVERSIBLE": 409,
    # optimistic concurrency
    "ERR_STALE_STOCK_ITEM_VERSION": 412,
    "ERR_STALE_SALE_VERSION": 412,
    # transport safety
    "ERR_LIQUID_LIMIT_EXCEEDED": 422,
    "ERR_SEALED_BAG_REQUIRED": 409,
    # referential coherence
    "ERR_EXCLUSIVITY_CONFLICT": 409,
    "ERR_PRODUCT_CATEGORY_MISMATCH": 422,
    "ERR_BRAND_SUSPENDED": 409,
    "ERR_TERMINAL_MISMATCH": 409,
    "ERR_ALLOWANCE_RULE_MISSING": 409,
    # temporal
    "ERR_SEAL_WINDOW_EXPIRED": 409,
    "ERR_DEPARTURE_PASSED": 409,
    "ERR_RESERVATION_WINDOW_INVALID": 422,
    "ERR_PERIOD_NOT_ENDED": 409,
    "ERR_EXCLUSIVITY_WINDOW_OVERLAP": 409,
    # assortment / governance
    "ERR_NATIONALITY_MIX_BELOW_THRESHOLD": 409,
    "ERR_ITINERARY_NOT_INTERNATIONAL": 409,
    "ERR_BOARDING_PASS_MISMATCH": 422,
    "ERR_EMPTY_BASKET": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_AUDIT_PERIOD_NOT_CLOSED": 409,
    "ERR_COUNTED_QTY_EXCEEDS_EXPECTED": 422,
    # fiscal / capacity
    "ERR_BONDED_STOCK_INSUFFICIENT": 409,
    "ERR_RESERVATION_CAPACITY_OVERLAP": 409,
    "ERR_VOID_AFTER_PERIOD_CLOSE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unrecognised role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorised for this operation.",
    "ERR_NOT_ITINERARY_OWNER": "The record does not trace back to the acting passenger's itinerary.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        if message is None:
            message = DEFAULT_MESSAGES.get(
                error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
            )
        self.message = message
