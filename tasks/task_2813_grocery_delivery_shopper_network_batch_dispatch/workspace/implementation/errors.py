"""Error catalog (PRD section 5) and the ApiError exception."""

ERROR_HTTP = {
    # auth & request shape
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    # not found
    "ERR_RETAILER_NOT_FOUND": 404,
    "ERR_CATALOG_ITEM_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_SHOPPER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_ORDER_LINE_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_REPLACEMENT_NOT_FOUND": 404,
    "ERR_RATING_NOT_FOUND": 404,
    "ERR_PAYOUT_NOT_FOUND": 404,
    "ERR_CREDIT_ENTRY_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # state preconditions
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ORDER_NOT_PLACED": 409,
    "ERR_ORDER_NOT_DELIVERED": 409,
    "ERR_BATCH_NOT_BUILDING": 409,
    "ERR_BATCH_NOT_OFFERED": 409,
    "ERR_BATCH_NOT_CLAIMED": 409,
    "ERR_BATCH_NOT_SHOPPING": 409,
    "ERR_BATCH_NOT_CHECKED_OUT": 409,
    "ERR_BATCH_NOT_ABANDONED": 409,
    "ERR_LINE_NOT_PICKABLE": 409,
    "ERR_REPLACEMENT_NOT_PENDING": 409,
    "ERR_PAYOUT_NOT_PROVISIONAL": 409,
    "ERR_SHOPPER_NOT_SUSPENDED": 409,
    "ERR_REAUTH_NOT_REQUIRED": 409,
    # referential integrity
    "ERR_ORDER_ALREADY_BATCHED": 409,
    "ERR_REPLACEMENT_RETAILER_MISMATCH": 422,
    "ERR_BATCH_EMPTY": 422,
    # EBT / SNAP safety
    "ERR_EBT_NOT_ENABLED": 422,
    "ERR_EBT_INELIGIBLE_REPLACEMENT": 422,
    # temporal
    "ERR_SHOPPER_WINDOW_CONFLICT": 409,
    "ERR_RETAILER_CONCURRENCY_CAP_REACHED": 409,
    "ERR_SHOP_WINDOW_NOT_OPEN": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_TIP_WINDOW_CLOSED": 409,
    "ERR_PAYOUT_WINDOW_OPEN": 409,
    # business constraints
    "ERR_SHOPPER_SUSPENDED": 403,
    "ERR_TIER_BELOW_BATCH_FLOOR": 403,
    "ERR_ITEM_OUT_OF_STOCK": 409,
    "ERR_WEIGHT_VARIANCE_EXCEEDED": 422,
    "ERR_DUPLICATE_RATING": 409,
    "ERR_TIP_ADJUSTMENT_LIMIT": 409,
    "ERR_REINSTATE_SCORE_TOO_LOW": 422,
    "ERR_NO_ELIGIBLE_SHOPPER": 422,
    # fiscal
    "ERR_SHOPPER_CAPACITY_EXCEEDED": 409,
    "ERR_ORDER_PAYMENT_HELD": 409,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognized authentication headers.",
    "ERR_UNAUTHORIZED_ROLE": "The acting role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
