"""Error catalogue and the ApiError exception carried through every rejection."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)
        self.message = message if message else DEFAULT_MESSAGES.get(error_id, error_id)


# HTTP status per error id -- PRD section 5 error catalogue.
HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ACTION_ROLE_FORBIDDEN": 403,
    "ERR_MERCHANT_OWNERSHIP_REQUIRED": 403,
    "ERR_TERMINAL_IDENTITY_MISMATCH": 403,
    "ERR_COMPLAINT_SOURCE_ROLE_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_MERCHANT_NOT_FOUND": 404,
    "ERR_COST_DOCUMENTATION_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_ARTIFACT_NOT_FOUND": 404,
    "ERR_TERMINAL_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_REFUND_NOT_FOUND": 404,
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_STALE_MERCHANT_VERSION": 412,
    "ERR_INVALID_PROGRAM_STATE": 409,
    "ERR_INVALID_REGISTRATION_STATE": 409,
    "ERR_INVALID_ARTIFACT_STATE": 409,
    "ERR_INVALID_TERMINAL_STATE": 409,
    "ERR_INVALID_COMPLAINT_STATE": 409,
    "ERR_INVALID_REFUND_STATE": 409,
    "ERR_SURCHARGE_PROHIBITED_JURISDICTION": 422,
    "ERR_CASH_DISCOUNT_PROHIBITED_JURISDICTION": 422,
    "ERR_PROGRAM_DISABLED_BY_PROHIBITION": 422,
    "ERR_DEBIT_SURCHARGE_FORBIDDEN": 422,
    "ERR_DEBIT_EXCLUSION_NOT_ENABLED": 422,
    "ERR_TERMINAL_PROGRAM_MISMATCH": 422,
    "ERR_JURISDICTION_SCOPE_MISMATCH": 422,
    "ERR_COST_DOCUMENTATION_MERCHANT_MISMATCH": 422,
    "ERR_REFUND_TRANSACTION_SCOPE_MISMATCH": 422,
    "ERR_COST_DOCUMENTATION_STALE": 409,
    "ERR_RATE_WINDOW_BUFFER_VIOLATION": 409,
    "ERR_DISCLOSURE_WINDOW_OVERLAP": 409,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 422,
    "ERR_PRODUCT_TIER_SCOPE_VIOLATION": 422,
    "ERR_BRAND_CONSISTENCY_VIOLATION": 422,
    "ERR_REGISTRATION_NOT_EFFECTIVE": 409,
    "ERR_DISCLOSURE_INCOMPLETE": 422,
    "ERR_PRICE_POSTING_REQUIRED": 422,
    "ERR_NO_RATE_RULE_IN_EFFECT": 422,
    "ERR_RECEIPT_LINE_ITEM_REQUIRED": 422,
    "ERR_DUPLICATE_JURISDICTION_STATE": 409,
    "ERR_DUPLICATE_TERMINAL_SERIAL": 409,
    "ERR_DUPLICATE_NETWORK_REGISTRATION": 409,
    "ERR_JURISDICTION_CAP_REQUIRED": 422,
    "ERR_SURCHARGE_CAP_EXCEEDED": 422,
    "ERR_SURCHARGE_AMOUNT_MISMATCH": 422,
    "ERR_REFUND_AMOUNT_EXCEEDS_SURCHARGE": 422,
    "ERR_REFUND_DUPLICATE_TRANSACTION": 409,
    "ERR_REMEDIATION_REFUNDS_PENDING": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers must both be present, non-empty and name a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this operation.",
    "ERR_ACTION_ROLE_FORBIDDEN": "The acting role is not permitted for the requested action.",
    "ERR_MERCHANT_OWNERSHIP_REQUIRED": "The acting merchant operator does not own the target resource.",
    "ERR_TERMINAL_IDENTITY_MISMATCH": "The acting terminal identity does not match the body terminal_id.",
    "ERR_COMPLAINT_SOURCE_ROLE_MISMATCH": "The acting role does not own this complaint source channel.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from performing this operation.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
    "ERR_JURISDICTION_CAP_REQUIRED": "surcharge_cap_pct must be non-null exactly when surcharge_permitted is true.",
}
