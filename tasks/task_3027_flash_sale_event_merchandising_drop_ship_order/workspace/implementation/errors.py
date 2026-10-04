"""Error catalogue for the flash-sale drop-ship API.

Every error identifier in the system, with its HTTP status, is declared here.
PRD §5 / SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """Carries an error_id / http status / human message through the stack."""

    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


# (error_id -> http status) — SCAFFOLD §1.6
CATALOG = {
    "ERR_MISSING_USER_CONTEXT": 400,
    "ERR_FORBIDDEN_FOR_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_SHOP_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_CONFIRMATION_NOT_FOUND": 404,
    "ERR_PURCHASE_ORDER_NOT_FOUND": 404,
    "ERR_POLINE_NOT_FOUND": 404,
    "ERR_VENDOR_SHIPMENT_NOT_FOUND": 404,
    "ERR_PARCEL_NOT_FOUND": 404,
    "ERR_RETURN_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_VENDOR_STANDING_BLOCKED": 409,
    "ERR_VENDOR_SUSPENDED": 409,
    "ERR_SHOP_SUSPENDED": 409,
    "ERR_PO_NOT_OWNED_BY_VENDOR": 409,
    "ERR_LISTING_EVENT_MISMATCH": 409,
    "ERR_CONFIRMATION_ORDER_MISMATCH": 409,
    "ERR_SHIPMENT_PO_MISMATCH": 409,
    "ERR_PARCEL_LINE_MISMATCH": 409,
    "ERR_SHIPMENT_EXCEEDS_PO": 409,
    "ERR_ALLOCATION_EXCEEDED": 409,
    "ERR_DUPLICATE_VENDOR_SKU": 409,
    "ERR_EMPTY_PURCHASE_ORDER": 409,
    "ERR_SHOP_SKU_LIMIT_EXCEEDED": 409,
    "ERR_LEDGER_IMMUTABLE": 409,
    "ERR_EVENT_NOT_STARTED": 409,
    "ERR_LISTING_NOT_REVEALED": 409,
    "ERR_CANCELLATION_WINDOW_CLOSED": 409,
    "ERR_DOCK_BUCKET_CAPACITY_EXCEEDED": 409,
    "ERR_FILL_RATE_BELOW_FLOOR": 409,
    "ERR_REFUND_OUTSTANDING": 409,
    "ERR_GOODWILL_CAP_EXCEEDED": 409,
    "ERR_OVERSELL_LIMIT_EXCEEDED": 409,
    "ERR_BRAND_WINDOW_OVERLAP": 409,
    "ERR_PAYOUT_EXCEEDS_BALANCE": 409,
    "ERR_DERIVED_FIELD_DRIFT": 409,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_USER_CONTEXT": "X-User-ID and X-User-Role headers are required.",
    "ERR_FORBIDDEN_FOR_ROLE": "The acting role is not authorized for this operation.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_STALE_VERSION": "The supplied expected version is stale.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this transition.",
    "ERR_VENDOR_STANDING_BLOCKED": "The vendor standing is PROBATION and no override was supplied.",
    "ERR_VENDOR_SUSPENDED": "The vendor standing is SUSPENDED.",
    "ERR_SHOP_SUSPENDED": "The shop is suspended or closed.",
    "ERR_DERIVED_FIELD_DRIFT": "A computed field no longer matched its calculation and was repaired.",
}


def fail(error_id, message=None):
    """Raise the catalogue error with its declared HTTP status."""
    raise ApiError(error_id, CATALOG.get(error_id, 500), message)


def invalid_request(message="The request body is malformed."):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)