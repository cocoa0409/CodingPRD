"""Error catalogue for the Parcel Dimensional Weight & Accessorial Billing API.

Every identifier and HTTP status here is taken verbatim from PRD section 5.
"""

HTTP_STATUS = {
    # auth
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_SHIPPER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_SHIPPER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_SERVICE_LEVEL_NOT_FOUND": 404,
    "ERR_SURCHARGE_WINDOW_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_ACCESSORIAL_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVOICE_LINE_NOT_FOUND": 404,
    "ERR_ADJUSTMENT_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_DUPLICATE_KEY": 409,
    # optimistic concurrency
    "ERR_STALE_SHIPPER_VERSION": 412,
    "ERR_STALE_SHIPMENT_VERSION": 412,
    "ERR_STALE_INVOICE_VERSION": 412,
    # state preconditions
    "ERR_SHIPPER_SUSPENDED": 409,
    "ERR_CONTRACT_NOT_ACTIVATABLE": 409,
    "ERR_WINDOW_NOT_IN_STATE": 409,
    "ERR_MEASUREMENT_FINAL": 409,
    "ERR_SHIPMENT_NOT_IN_TRANSIT": 409,
    "ERR_ACCESSORIAL_NOT_WAIVABLE": 409,
    "ERR_INVOICE_NOT_IN_STATE": 409,
    "ERR_INVOICE_NOT_ADJUSTABLE": 409,
    "ERR_ADJUSTMENT_NOT_PENDING": 409,
    "ERR_INVOICE_NOT_DISPUTABLE": 409,
    "ERR_DISPUTE_NOT_IN_STATE": 409,
    "ERR_CLAIM_NOT_ADJUDICABLE": 409,
    "ERR_SHIPMENT_NOT_DELIVERED": 409,
    "ERR_LINE_ALREADY_FROZEN": 409,
    # temporal
    "ERR_INVALID_PERIOD": 422,
    "ERR_CONTRACT_PERIOD_OVERLAP": 409,
    "ERR_SURCHARGE_WINDOW_OVERLAP": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_CLAIM_WINDOW_CLOSED": 422,
    # referential
    "ERR_DUPLICATE_DISPUTE": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_SHIPMENT_ALREADY_BILLED": 409,
    "ERR_NO_ACTIVE_CONTRACT": 422,
    "ERR_RATE_ROW_MISSING": 422,
    "ERR_DISPUTED_CODE_NOT_ASSESSED": 422,
    # business constraints
    "ERR_NO_BILLABLE_SHIPMENTS": 422,
    "ERR_SCAN_TOLERANCE_UNRESOLVED": 409,
    "ERR_EVIDENCE_ROUNDS_EXHAUSTED": 409,
    "ERR_EVIDENCE_REQUIRED": 422,
    "ERR_SERVICE_NOT_GUARANTEED": 422,
    "ERR_SHIPMENT_NOT_INVOICED": 422,
    "ERR_GUARANTEE_SUSPENDED": 422,
    "ERR_SHIPMENT_NOT_LATE": 422,
    # fiscal
    "ERR_ADJUSTMENT_EXCEEDS_LINE": 422,
    "ERR_CREDIT_EXCEEDS_INVOICE_NET": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask handler."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words
