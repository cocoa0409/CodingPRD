"""Error catalogue — PRD section 5. error_id string -> HTTP status."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_VALIDATION": 400,
    "ERR_MUNICIPALITY_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_JOBSITE_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_CREW_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_RECONCILIATION_NOT_FOUND": 404,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_STALE_VERSION": 412,
    "ERR_QUOTE_STATE": 409,
    "ERR_PERMIT_STATE": 409,
    "ERR_CONTRACT_STATE": 409,
    "ERR_WORK_ORDER_STATE": 409,
    "ERR_INVOICE_STATE": 409,
    "ERR_RECONCILIATION_STATE": 409,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_PERMIT_WINDOW_ELAPSED": 409,
    "ERR_WIND_LOAD_NOT_PERMITTED": 409,
    "ERR_CREW_NOT_CERTIFIED": 409,
    "ERR_PERMIT_LEAD_TIME_NOT_MET": 409,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_CREW_CAPACITY_EXCEEDED": 409,
    "ERR_BILLING_PERIOD_INVALID": 409,
    "ERR_CLOSURE_CAPACITY_EXCEEDED": 409,
    "ERR_PERMIT_REVISION_LIMIT": 409,
    "ERR_INSUFFICIENT_FLEET": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_INVALID_ADDON_CATEGORY": 409,
    "ERR_INVALID_PHASE_MOVE": 409,
    "ERR_PANEL_COUNT_MISMATCH": 409,
    "ERR_BELOW_MINIMUM_TERM": 409,
    "ERR_ACCOUNT_CREDIT_HOLD": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 409,
}

# not-found error per entity kind (ladder rungs 4 and 5)
NOT_FOUND = {
    "municipality": "ERR_MUNICIPALITY_NOT_FOUND",
    "account": "ERR_ACCOUNT_NOT_FOUND",
    "jobsite": "ERR_JOBSITE_NOT_FOUND",
    "product": "ERR_PRODUCT_NOT_FOUND",
    "crew": "ERR_CREW_NOT_FOUND",
    "quote": "ERR_QUOTE_NOT_FOUND",
    "permit": "ERR_PERMIT_NOT_FOUND",
    "contract": "ERR_CONTRACT_NOT_FOUND",
    "work_order": "ERR_WORK_ORDER_NOT_FOUND",
    "invoice": "ERR_INVOICE_NOT_FOUND",
    "reconciliation": "ERR_RECONCILIATION_NOT_FOUND",
}

# state error per entity kind (ladder rung 9)
STATE_ERROR = {
    "quote": "ERR_QUOTE_STATE",
    "permit": "ERR_PERMIT_STATE",
    "contract": "ERR_CONTRACT_STATE",
    "work_order": "ERR_WORK_ORDER_STATE",
    "invoice": "ERR_INVOICE_STATE",
    "reconciliation": "ERR_RECONCILIATION_STATE",
}


class ApiError(Exception):
    """Raised anywhere in a request; translated into the PRD error envelope."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return "Request refused: %s." % error_id


def fail(error_id, message=None):
    raise ApiError(error_id, message)
