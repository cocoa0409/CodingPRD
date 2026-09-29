"""Error catalogue (PRD §5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CLIENT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PIECE_COUNT": 400,
    "ERR_INTERVAL_INVALID": 400,
    # existence
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_PERMIT_ACCOUNT_NOT_FOUND": 404,
    "ERR_MAIL_JOB_NOT_FOUND": 404,
    "ERR_BATCH_NOT_FOUND": 404,
    "ERR_BATCH_MEMBER_NOT_FOUND": 404,
    "ERR_CONTAINER_NOT_FOUND": 404,
    "ERR_ENTRY_FACILITY_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_DROP_SHIPMENT_NOT_FOUND": 404,
    "ERR_SERVICE_LEVEL_RECORD_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # state
    "ERR_INVALID_JOB_STATE": 409,
    "ERR_JOB_ALREADY_POOLED": 409,
    "ERR_INVALID_BATCH_STATE": 409,
    "ERR_INVALID_STATEMENT_STATE": 409,
    "ERR_INVALID_SHIPMENT_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_CLIENT_SUSPENDED": 409,
    "ERR_PERMIT_ACCOUNT_NOT_ACTIVE": 409,
    "ERR_ENTRY_FACILITY_CLOSED": 409,
    "ERR_STATEMENT_NOT_ACCEPTED": 409,
    "ERR_PERMIT_ANNUAL_FEE_LAPSED": 409,
    "ERR_PERMIT_HAS_RESERVED_FUNDS": 409,
    "ERR_DUPLICATE_CLIENT_CODE": 409,
    "ERR_DUPLICATE_PERMIT_NUMBER": 409,
    "ERR_DUPLICATE_FACILITY_CODE": 409,
    # business rules
    "ERR_PERMIT_CLIENT_MISMATCH": 422,
    "ERR_MOVE_UPDATE_STALE": 422,
    "ERR_ADDRESS_QUALITY_BELOW_MINIMUM": 422,
    "ERR_MAIL_CLASS_MISMATCH": 422,
    "ERR_PROCESSING_CATEGORY_MISMATCH": 422,
    "ERR_COMMINGLE_OPT_OUT": 422,
    "ERR_BATCH_HAS_NO_CONTAINERS": 422,
    "ERR_CONTAINER_NOT_QUALIFIED": 422,
    "ERR_CONTAINER_PIECE_MISMATCH": 422,
    "ERR_SHIPMENT_ALREADY_SCHEDULED": 409,
    "ERR_SHIPMENT_WINDOW_IN_PAST": 422,
    "ERR_DOCK_CAPACITY_EXCEEDED": 409,
    "ERR_OUTSIDE_APPOINTMENT_WINDOW": 422,
    "ERR_DELIVERY_ALREADY_SCANNED": 409,
    "ERR_NO_VERIFICATION_FINDINGS": 422,
    "ERR_BILLING_PERIOD_OVERLAP": 409,
    "ERR_NO_BILLABLE_JOBS": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_INSUFFICIENT_POSTAGE_BALANCE": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_CLIENT_SCOPE_VIOLATION": "A ClientContact may only act within its own client.",
    "ERR_SEGREGATION_OF_DUTIES": "The user who filed the statement may not verify it.",
    "ERR_INVALID_REQUEST": "The request body or query string is invalid.",
    "ERR_INVALID_PIECE_COUNT": "A declared piece, pallet or money figure is out of range.",
    "ERR_INTERVAL_INVALID": "The end instant must be strictly after the start instant.",
}


class ApiError(Exception):
    """Raised anywhere in request handling; rendered as the standard error envelope."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
        )
        super().__init__(self.message)
