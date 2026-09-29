"""Error catalogue (PRD section 5 / scaffold section 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_CHANNEL_NOT_FOUND": 404,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_FARE_FILING_NOT_FOUND": 404,
    "ERR_ANCILLARY_NOT_FOUND": 404,
    "ERR_BUNDLE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SERVICE_REQUEST_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_CONNECTIVITY_TEST_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PARTNER_VERSION": 412,
    "ERR_STALE_FARE_FILING_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_OFFER_NOT_PUBLISHED": 409,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_FARE_FILING_NOT_ACTIVE": 409,
    "ERR_AGREEMENT_NOT_SIGNED": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_CERTIFICATION_ALREADY_OPEN": 409,
    "ERR_CONTRACT_NOT_IN_EFFECT": 409,
    "ERR_FARE_SALE_WINDOW_CLOSED": 409,
    "ERR_FARE_SALE_WINDOW_OVERLAP": 409,
    "ERR_TEST_SLOT_CONFLICT": 409,
    "ERR_TEST_ENV_CAPACITY_EXCEEDED": 409,
    "ERR_DUPLICATE_CHANNEL_CODE": 409,
    # safety / referential / constraint / fiscal
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_DISCLOSURE_INCOMPLETE": 422,
    "ERR_SERVICING_NOT_SUPPORTED_ON_CHANNEL": 422,
    "ERR_PRIVATE_FARE_REQUIRES_CONTRACT": 422,
    "ERR_CORPORATE_TRACKING_REF_MISSING": 422,
    "ERR_CORPORATE_TRACKING_REF_INVALID": 422,
    "ERR_PARTNER_TYPE_NOT_ELIGIBLE": 422,
    "ERR_TRAVEL_DATE_OUT_OF_WINDOW": 422,
    "ERR_NEGOTIATION_ROUND_LIMIT": 422,
    "ERR_CONTENT_TIER_INSUFFICIENT": 422,
    "ERR_READINESS_BELOW_MINIMUM": 422,
    "ERR_CONTRACT_CAP_EXCEEDED": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    # fallback
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request is malformed.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not legal from the current state.",
    "ERR_INTERNAL": "Internal server error.",
}
