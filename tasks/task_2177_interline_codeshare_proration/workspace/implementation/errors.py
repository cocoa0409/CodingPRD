"""Error catalogue for the Interline & Codeshare Proration API (PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_CARRIER_OWNERSHIP_REQUIRED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CARRIER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_TICKET_NOT_FOUND": 404,
    "ERR_COUPON_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_MEMO_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_OPEN": 409,
    "ERR_PERIOD_NOT_CLOSED": 409,
    "ERR_INVOICE_STATE_INVALID": 409,
    "ERR_INVOICE_NOT_CLEARED": 409,
    "ERR_MEMO_STATE_INVALID": 409,
    "ERR_COUPON_STATE_INVALID": 409,
    "ERR_TICKET_NOT_FINAL_PRORATED": 409,
    "ERR_AGREEMENT_STATE_INVALID": 409,
    "ERR_SAMPLE_STATE_INVALID": 409,
    "ERR_CARRIER_STATE_INVALID": 409,
    "ERR_TICKET_NOT_PRORATED": 409,
    "ERR_CARRIER_SUSPENDED": 409,
    "ERR_OPERATING_CARRIER_SUSPENDED": 409,
    "ERR_AGREEMENT_PERIOD_OVERLAP": 409,
    "ERR_PERIOD_WINDOW_OVERLAP": 409,
    "ERR_MEMO_WINDOW_EXPIRED": 409,
    "ERR_ARBITRATION_NOT_ELIGIBLE": 409,
    "ERR_AUDIT_TIME_BARRED": 409,
    "ERR_COUPON_NOT_ON_INVOICE": 422,
    "ERR_COUPON_CARRIER_MISMATCH": 422,
    "ERR_CURRENCY_MISMATCH": 422,
    "ERR_COUPON_NOT_IN_SAMPLE": 422,
    "ERR_DUPLICATE_TICKET_NUMBER": 409,
    "ERR_COUPON_SEQUENCE_INVALID": 422,
    "ERR_DUPLICATE_FACTOR_SECTOR": 409,
    "ERR_FACTOR_FIELD_MISMATCH": 422,
    "ERR_DUPLICATE_EXCHANGE_RATE": 409,
    "ERR_NO_PRORATABLE_COUPONS": 422,
    "ERR_MEMO_STAGE_EXHAUSTED": 409,
    "ERR_COUPON_ALREADY_INVOICED": 409,
    "ERR_EMPTY_AUDIT_POPULATION": 422,
    "ERR_COUPON_NOT_IN_POPULATION": 422,
    "ERR_SPA_OVERALLOCATION": 422,
    "ERR_MEMO_AMOUNT_EXCEEDS_COUPON": 422,
    "ERR_MEMO_AMOUNT_EXCEEDS_INVOICE": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 409,
    "ERR_NO_EXCHANGE_RATE": 422,
    "ERR_STALE_INVOICE_VERSION": 412,
    "ERR_STALE_TICKET_VERSION": 412,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this operation.",
    "ERR_CARRIER_OWNERSHIP_REQUIRED": "The acting carrier does not own this resource.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_CARRIER_NOT_FOUND": "Carrier not found.",
    "ERR_AGREEMENT_NOT_FOUND": "Prorate agreement not found.",
    "ERR_TICKET_NOT_FOUND": "Ticket not found.",
    "ERR_COUPON_NOT_FOUND": "Coupon not found.",
    "ERR_PERIOD_NOT_FOUND": "Settlement period not found.",
    "ERR_INVOICE_NOT_FOUND": "Billing invoice not found.",
    "ERR_MEMO_NOT_FOUND": "Rejection memo not found.",
    "ERR_SAMPLE_NOT_FOUND": "Audit sample not found.",
}
