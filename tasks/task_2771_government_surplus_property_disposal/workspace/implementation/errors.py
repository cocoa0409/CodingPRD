"""Error catalogue.  Error ids and HTTP statuses come from PRD section 5 plus the
prose-only code ERR_LEDGER_WOULD_GO_NEGATIVE described in PRD section 3.9."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message if message else DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status if http_status is not None else STATUS.get(error_id, 400)


STATUS = {
    # auth / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_AGENCY_SCOPE": 403,
    "ERR_FORBIDDEN_BIDDER_SCOPE": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_CONDITIONAL_FIELD_REQUIRED": 422,
    "ERR_FUTURE_DATE": 422,
    # existence
    "ERR_AGENCY_NOT_FOUND": 404,
    "ERR_TURN_IN_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_SCREENING_CYCLE_NOT_FOUND": 404,
    "ERR_SCREENING_REQUEST_NOT_FOUND": 404,
    "ERR_TRANSFER_ORDER_NOT_FOUND": 404,
    "ERR_VENUE_NOT_FOUND": 404,
    "ERR_AUCTION_LOT_NOT_FOUND": 404,
    "ERR_BIDDER_NOT_FOUND": 404,
    "ERR_SALE_INVOICE_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    # uniqueness / graph
    "ERR_DUPLICATE_AGENCY_CODE": 409,
    "ERR_DUPLICATE_VENUE_CODE": 409,
    "ERR_DUPLICATE_BIDDER_EMAIL": 409,
    "ERR_ASSET_COMPONENT_CYCLE": 422,
    # concurrency
    "ERR_STALE_ASSET_VERSION": 412,
    "ERR_STALE_LOT_VERSION": 412,
    # segregation of duties
    "ERR_SEGREGATION_OF_DUTIES": 409,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_TURN_IN_NOT_DRAFT": 409,
    "ERR_TURN_IN_NOT_ASSESSED": 409,
    "ERR_ASSET_NOT_ASSESSABLE": 409,
    "ERR_ASSET_NOT_DISPOSABLE": 409,
    "ERR_AGENCY_SUSPENDED": 409,
    "ERR_VENUE_CLOSED": 409,
    "ERR_LOT_NOT_OPEN": 409,
    "ERR_BIDDER_NOT_REGISTERED": 403,
    # compliance / safety
    "ERR_FEDERAL_USE_PERIOD_ACTIVE": 409,
    "ERR_SANITIZATION_NOT_CERTIFIED": 409,
    "ERR_DEMIL_NOT_CERTIFIED": 409,
    "ERR_END_USE_CERTIFICATE_REQUIRED": 409,
    "ERR_CLEARANCE_METHOD_MISMATCH": 422,
    "ERR_CLEARANCE_NOT_APPLICABLE": 409,
    "ERR_DONEE_CERTIFICATION_INVALID": 409,
    # policy / scheduling
    "ERR_TIER_PRIORITY_VIOLATION": 409,
    "ERR_ODOMETER_DISCLOSURE_REQUIRED": 422,
    "ERR_LIEN_NOT_RELEASED": 409,
    "ERR_REQUEST_CYCLE_MISMATCH": 409,
    "ERR_TIER_WINDOW_EXPIRED": 409,
    "ERR_TIER_WINDOW_OPEN": 409,
    "ERR_VENUE_CAPACITY_CONFLICT": 409,
    "ERR_ASSET_WINDOW_CONFLICT": 409,
    "ERR_INVALID_WINDOW": 422,
    # fiscal
    "ERR_BID_BELOW_RESERVE": 422,
    "ERR_BID_INCREMENT_NOT_MET": 422,
    "ERR_BID_DEPOSIT_INSUFFICIENT": 402,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_DISTRIBUTION_BASIS_UNAVAILABLE": 409,
    "ERR_DISTRIBUTION_ALREADY_POSTED": 409,
    "ERR_LEDGER_WOULD_GO_NEGATIVE": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or unresolvable",
    "ERR_UNAUTHORIZED": "The caller's role is not authorised for this operation",
    "ERR_FORBIDDEN_AGENCY_SCOPE": "The caller may only act within its own agency",
    "ERR_FORBIDDEN_BIDDER_SCOPE": "The caller may only act on its own bidder record",
    "ERR_INVALID_REQUEST": "The request body is malformed",
    "ERR_INVALID_ENUM_VALUE": "An enum-typed field carries a value outside its declared set",
    "ERR_INVALID_PAGINATION": "The pagination parameters are out of range",
    "ERR_CONDITIONAL_FIELD_REQUIRED": "A conditionally required field is missing",
    "ERR_FUTURE_DATE": "A date field lies in the future relative to the logical clock",
    "ERR_INVALID_STATE": "The operation is not admissible from the current state",
}
