"""Error catalogue (PRD 5) — 54 error ids with their HTTP status codes."""

ERROR_STATUS = {
    # --- auth / identity ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- not found ---
    "ERR_HOST_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_VIEWER_NOT_FOUND": 404,
    "ERR_SHOW_NOT_FOUND": 404,
    "ERR_STREAM_CHANNEL_NOT_FOUND": 404,
    "ERR_HOST_BOOKING_NOT_FOUND": 404,
    "ERR_LINEUP_SLOT_NOT_FOUND": 404,
    "ERR_FLASH_OFFER_NOT_FOUND": 404,
    "ERR_DISCLOSURE_RECORD_NOT_FOUND": 404,
    "ERR_CART_NOT_FOUND": 404,
    "ERR_CART_ITEM_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_INTERACTION_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    # --- concurrency ---
    "ERR_STALE_LINEUP_SLOT_VERSION": 412,
    "ERR_STALE_CART_VERSION": 412,
    # --- own-entity state ---
    "ERR_INVALID_SHOW_STATE": 409,
    "ERR_INVALID_BOOKING_STATE": 409,
    "ERR_INVALID_CHANNEL_STATE": 409,
    "ERR_INVALID_DISCLOSURE_STATE": 409,
    "ERR_INVALID_OFFER_STATE": 409,
    "ERR_INVALID_CART_STATE": 409,
    "ERR_INVALID_ORDER_STATE": 409,
    "ERR_INVALID_INTERACTION_STATE": 409,
    # --- cross-entity state ---
    "ERR_OFFER_NOT_ACTIVE": 409,
    "ERR_SHOW_NOT_ENDED": 409,
    # --- compliance business rules ---
    "ERR_CLAIM_NOT_SUBSTANTIATED": 422,
    "ERR_DISCLOSURE_NOT_ACKNOWLEDGED": 422,
    "ERR_HOST_CERTIFICATION_EXPIRED": 422,
    # --- temporal / overlap ---
    "ERR_HOST_BOOKING_OVERLAP": 409,
    "ERR_OFFER_WINDOW_OVERLAP": 409,
    "ERR_OFFER_WINDOW_CLOSED": 409,
    "ERR_GO_LIVE_WINDOW_CLOSED": 409,
    "ERR_RECOVERY_WINDOW_CLOSED": 409,
    "ERR_OFFER_SHOW_MISMATCH": 422,
    # --- production readiness ---
    "ERR_PRIMARY_HOST_CONFLICT": 409,
    "ERR_PRIMARY_HOST_MISSING": 422,
    "ERR_LINEUP_EMPTY": 422,
    "ERR_SIMULCAST_NOT_READY": 422,
    # --- interactive ---
    "ERR_VIEWER_MUTED": 403,
    "ERR_POLL_NOT_OPEN": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_DEFERRAL_LIMIT_REACHED": 409,
    # --- replay merchandising ---
    "ERR_REPLAY_MARKER_NOT_PUBLISHED": 409,
    "ERR_MARKER_OFFSET_OUT_OF_RANGE": 422,
    # --- cart / inventory boundaries ---
    "ERR_EMPTY_CART": 422,
    "ERR_NO_RECOVERABLE_ITEMS": 409,
    "ERR_CART_ITEM_LIMIT": 422,
    "ERR_OFFER_QTY_EXCEEDED": 422,
    "ERR_INSUFFICIENT_INVENTORY": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower()
    return "Request rejected: " + words + "."
