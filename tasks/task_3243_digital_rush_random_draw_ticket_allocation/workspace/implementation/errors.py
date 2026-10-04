"""Error catalogue and exception type for the digital rush / draw API."""

HTTP_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_STALE_VERSION": 412,
    "ERR_PRODUCTION_NOT_FOUND": 404,
    "ERR_PERFORMANCE_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_PURCHASE_NOT_FOUND": 404,
    "ERR_DRAW_ENTRY_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_QUEUE_POSITION_NOT_FOUND": 404,
    "ERR_DESK_NOT_FOUND": 404,
    "ERR_HANDOFF_NOT_FOUND": 404,
    "ERR_REFUND_NOT_FOUND": 404,
    "ERR_EXCHANGE_NOT_FOUND": 404,
    "ERR_PATRON_NOT_FOUND": 404,
    "ERR_MARKET_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_PRODUCTION_SUSPENDED": 409,
    "ERR_DRAW_WINDOW_CLOSED": 409,
    "ERR_DUPLICATE_DRAW_ENTRY": 409,
    "ERR_DRAW_NO_ELIGIBLE_ENTRIES": 409,
    "ERR_CLAIM_DEADLINE_PASSED": 409,
    "ERR_RUSH_NOT_RELEASED": 409,
    "ERR_QUEUE_ADMISSION_EXPIRED": 409,
    "ERR_QUEUE_POSITION_EXISTS": 409,
    "ERR_SEAT_ALREADY_HELD": 409,
    "ERR_ORDER_BLOCK_CAPACITY": 409,
    "ERR_MARKET_SHARE_CAP_EXCEEDED": 409,
    "ERR_ALLOCATION_EXHAUSTED": 409,
    "ERR_PER_ORDER_LIMIT_EXCEEDED": 409,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_HANDOFF_TOKEN_INVALID": 422,
    "ERR_DESK_CAPACITY_REACHED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_FORBIDDEN": "The acting role is not permitted on this operation.",
    "ERR_SOD_VIOLATION": "The acting operator must differ from the operator who recorded the prior step of this workflow.",
    "ERR_STALE_VERSION": "The submitted expected_*_version no longer matches the current version of the row.",
    "ERR_REFERENCE_NOT_FOUND": "An entity reference supplied in the request body does not resolve.",
    "ERR_INVALID_STATE": "The target row is not in a state that permits the requested transition.",
    "ERR_ALREADY_TERMINAL": "The target row has already reached a terminal state.",
    "ERR_PRODUCTION_SUSPENDED": "The production behind this allocation or performance is SUSPENDED.",
    "ERR_DRAW_WINDOW_CLOSED": "The draw entry window is not open.",
    "ERR_DUPLICATE_DRAW_ENTRY": "The patron already holds a non-cancelled entry for this draw allocation.",
    "ERR_DRAW_NO_ELIGIBLE_ENTRIES": "The draw execution found no ENTERED entry whose patron is ACTIVE.",
    "ERR_CLAIM_DEADLINE_PASSED": "The claim deadline on this winning draw entry has been reached.",
    "ERR_RUSH_NOT_RELEASED": "The rush allocation is not RELEASED for the current epoch, or its release instant has not been reached.",
    "ERR_QUEUE_ADMISSION_EXPIRED": "The queue admission relied upon by this order has already lapsed.",
    "ERR_QUEUE_POSITION_EXISTS": "The patron already holds a WAITING or ADMITTED queue position for this performance.",
    "ERR_SEAT_ALREADY_HELD": "The seat label overlaps a non-terminal hold on this performance.",
    "ERR_ORDER_BLOCK_CAPACITY": "The order's contiguous seat run intersects an existing order block.",
    "ERR_MARKET_SHARE_CAP_EXCEEDED": "The release would push discounted inventory above the permitted share of the house.",
    "ERR_ALLOCATION_EXHAUSTED": "The order or claim would take the day's sold count past the allocation's release ceiling.",
    "ERR_PER_ORDER_LIMIT_EXCEEDED": "The requested quantity exceeds the allocation's per-order limit.",
    "ERR_REFUND_WINDOW_CLOSED": "The production's refund window has closed and the allocation is not refundable.",
    "ERR_HANDOFF_TOKEN_INVALID": "The submitted redemption_code does not equal the purchase handoff token, or the purchase has already recorded a failed handoff.",
    "ERR_DESK_CAPACITY_REACHED": "The assigned concierge desk is SATURATED or has reached its daily capacity.",
}


class ApiError(Exception):
    """Carries an error_id and its HTTP status; rendered in the error envelope."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "The request could not be completed."
        )
        self.http_status = http_status or HTTP_BY_ERROR.get(error_id, 400)
        super().__init__("%s: %s" % (self.error_id, self.message))