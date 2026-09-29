"""Error catalogue (PRD section 5). Exactly 45 identifiers."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message if message else DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # Authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # Existence
    "ERR_DISTRIBUTOR_NOT_FOUND": 404,
    "ERR_ARTIST_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_RELEASE_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_MARKETING_SPEND_NOT_FOUND": 404,
    "ERR_REVENUE_REPORT_NOT_FOUND": 404,
    "ERR_PHYSICAL_RUN_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    # Shape
    "ERR_INVALID_REQUEST": 400,
    # Optimistic concurrency
    "ERR_STALE_DEAL_VERSION": 412,
    "ERR_STALE_RUN_VERSION": 412,
    # State gates
    "ERR_INVALID_DEAL_STATE": 409,
    "ERR_INVALID_RELEASE_STATE": 409,
    "ERR_INVALID_AGREEMENT_STATE": 409,
    "ERR_INVALID_SPEND_STATE": 409,
    "ERR_INVALID_REPORT_STATE": 409,
    "ERR_INVALID_RUN_STATE": 409,
    "ERR_INVALID_STATEMENT_STATE": 409,
    "ERR_DEAL_NOT_COLLECTING": 409,
    "ERR_AGREEMENT_NOT_STATEMENTABLE": 409,
    "ERR_RELEASE_NOT_PROMOTABLE": 409,
    # Referential / uniqueness
    "ERR_RATE_CARD_OVERLAP": 409,
    "ERR_STATEMENT_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_UPC": 409,
    "ERR_OPEN_OBJECTIONS_BLOCK_CLOSE": 409,
    "ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS": 422,
    "ERR_RATE_CARD_NOT_FOUND": 422,
    "ERR_PROVISIONAL_NOT_ISSUABLE": 422,
    # Temporal
    "ERR_PERIOD_OUTSIDE_TERM": 422,
    "ERR_TERM_NOT_ENDED": 422,
    "ERR_POST_TERM_COLLECTION_ACTIVE": 422,
    "ERR_OBJECTION_WINDOW_CLOSED": 422,
    "ERR_OBJECTION_WINDOW_OPEN": 422,
    "ERR_AUDIT_WINDOW_EXPIRED": 422,
    # Fiscal ceilings
    "ERR_DISPUTED_AMOUNT_EXCEEDS_NET": 422,
    "ERR_MARKETING_BUDGET_EXCEEDED": 422,
    "ERR_ADVANCE_ALLOCATION_EXCEEDED": 422,
    "ERR_INVENTORY_OBLIGATION_BREACH": 422,
    "ERR_RETURNS_EXCEED_SHIPPED": 422,
    "ERR_LIQUIDATION_EXCEEDS_RESERVE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or blank.",
    "ERR_ROLE_NOT_PERMITTED": "The caller's role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The same actor may not perform both halves of this control.",
    "ERR_DISTRIBUTOR_NOT_FOUND": "Distributor not found.",
    "ERR_ARTIST_NOT_FOUND": "Artist not found.",
    "ERR_DEAL_NOT_FOUND": "Distribution deal not found.",
    "ERR_RELEASE_NOT_FOUND": "Release not found.",
    "ERR_AGREEMENT_NOT_FOUND": "Artist agreement not found.",
    "ERR_MARKETING_SPEND_NOT_FOUND": "Marketing spend not found.",
    "ERR_REVENUE_REPORT_NOT_FOUND": "DSP revenue report not found.",
    "ERR_PHYSICAL_RUN_NOT_FOUND": "Physical run not found.",
    "ERR_STATEMENT_NOT_FOUND": "Artist statement not found.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_STALE_DEAL_VERSION": "The supplied deal version is stale.",
    "ERR_STALE_RUN_VERSION": "The supplied run version is stale.",
    "ERR_INVALID_DEAL_STATE": "The deal is not in a state that permits this operation.",
    "ERR_INVALID_RELEASE_STATE": "The release is not in a state that permits this operation.",
    "ERR_INVALID_AGREEMENT_STATE": "The agreement is not in a state that permits this operation.",
    "ERR_INVALID_SPEND_STATE": "The marketing spend is not in a state that permits this operation.",
    "ERR_INVALID_REPORT_STATE": "The revenue report is not in a state that permits this operation.",
    "ERR_INVALID_RUN_STATE": "The physical run is not in a state that permits this operation.",
    "ERR_INVALID_STATEMENT_STATE": "The statement is not in a state that permits this operation.",
    "ERR_DEAL_NOT_COLLECTING": "The deal is not collecting revenue.",
    "ERR_AGREEMENT_NOT_STATEMENTABLE": "The agreement is not accountable for statements.",
    "ERR_RELEASE_NOT_PROMOTABLE": "The release may no longer be promoted.",
    "ERR_RATE_CARD_OVERLAP": "An overlapping rate card already exists.",
    "ERR_STATEMENT_PERIOD_OVERLAP": "The statement period overlaps an existing final period.",
    "ERR_DUPLICATE_UPC": "The UPC is already registered.",
    "ERR_OPEN_OBJECTIONS_BLOCK_CLOSE": "An unresolved objection blocks closure.",
    "ERR_STATEMENT_PERIOD_NOT_CONTIGUOUS": "The statement period is not contiguous with the prior period.",
    "ERR_RATE_CARD_NOT_FOUND": "No effective rate card covers a reported line.",
    "ERR_PROVISIONAL_NOT_ISSUABLE": "A provisional statement may not be issued for this agreement.",
    "ERR_PERIOD_OUTSIDE_TERM": "The period falls outside the deal's accountable span.",
    "ERR_TERM_NOT_ENDED": "The contractual term has not ended.",
    "ERR_POST_TERM_COLLECTION_ACTIVE": "The post-term collection window is still active.",
    "ERR_OBJECTION_WINDOW_CLOSED": "The objection window has closed.",
    "ERR_OBJECTION_WINDOW_OPEN": "The objection window is still open.",
    "ERR_AUDIT_WINDOW_EXPIRED": "The audit-rights window has expired.",
    "ERR_DISPUTED_AMOUNT_EXCEEDS_NET": "The disputed amount exceeds the net payable.",
    "ERR_MARKETING_BUDGET_EXCEEDED": "The marketing budget would be exceeded.",
    "ERR_ADVANCE_ALLOCATION_EXCEEDED": "The advance allocation would be exceeded.",
    "ERR_INVENTORY_OBLIGATION_BREACH": "The inventory retention obligation would be breached.",
    "ERR_RETURNS_EXCEED_SHIPPED": "Cumulative returns would exceed units shipped.",
    "ERR_LIQUIDATION_EXCEEDS_RESERVE": "The liquidation exceeds the reserve still held.",
}
