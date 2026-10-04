"""Error catalogue and the API exception type.

Every error_id below is read verbatim from SCAFFOLD.yaml §1.6 (the Error Code
Catalogue) and PRD.md §5. The HTTP status is part of the catalogue and is
carried on the exception so a raise site never has to restate it.
"""


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the app error handler."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_CONTEXT_HEADER": 400,
    "ERR_FORBIDDEN_FOR_ACTOR": 403,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_ITINERARY_NOT_FOUND": 404,
    "ERR_FREEZE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_SOD_VIOLATION": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ITINERARY_NOT_PLANNED": 409,
    "ERR_NOTIFICATION_SUPPRESSED": 409,
    "ERR_ROUTE_EXPOSURE_PROFILE": 422,
    "ERR_CUSTODY_INSUFFICIENT": 422,
    "ERR_ROUTE_RESTRICTED": 409,
    "ERR_GUARANTEE_EXPOSURE_EXCEEDED": 422,
    "ERR_PRODUCT_TYPE_MISMATCH": 422,
    "ERR_HEDGE_DUPLICATE_COVERAGE": 409,
    "ERR_DUPLICATE_SEQUENCE_INDEX": 409,
    "ERR_DISCLOSURE_NOT_ACKNOWLEDGED": 422,
    "ERR_PRICE_FIELD_MISSING": 422,
    "ERR_STALE_VERSION": 412,
    "ERR_NO_OVERSHOOT": 422,
    "ERR_PAYMENT_RETIRED": 409,
    "ERR_PAYMENT_OVER_ALLOCATED": 422,
    "ERR_CLAIM_NON_CONFORMANT": 422,
    "ERR_CANCELLATION_ALREADY_EXERCISED": 409,
    "ERR_DISRUPTION_BELOW_MINIMUM": 422,
    "ERR_PREMIUM_NOT_PAYABLE": 409,
    "ERR_CHANGE_ALREADY_OPEN": 409,
    "ERR_INSUFFICIENT_BONUS_DAYS": 422,
    "ERR_OPTION_HOLD_LAPSED": 409,
    "ERR_OPTION_NOT_OFFERED": 409,
    "ERR_OPTION_NOT_IN_EVENT": 422,
    "ERR_NO_SEATS_LEFT": 409,
    "ERR_CURVE_UNPUBLISHED": 409,
    "ERR_WATCH_EXPIRED": 409,
    "ERR_ROUTE_ITINERARY_MISMATCH": 422,
    "ERR_DESK_ODD_RATIO": 422,
    "ERR_MANIFEST_UNSETTLED": 409,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    "ERR_INVALID_REQUEST": 400,
}


def fail(error_id, message=""):
    """Raise an ApiError using the catalogued HTTP status for error_id."""
    raise ApiError(error_id, message or error_id, ERROR_HTTP.get(error_id, 400))