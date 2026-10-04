"""Error catalogue and helpers for the Payroll Employment Verification Exchange."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_OWNERSHIP": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_VERIFIER_RESTRICTED": 403,
    "ERR_WORKER_OPT_OUT": 403,
    "ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE": 403,
    "ERR_PRODUCT_NOT_PERMITTED_FOR_CLASS": 403,
    "ERR_EMPLOYER_FROZEN": 403,
    "ERR_AUTHORIZATION_OVERLAP": 409,
    "ERR_REVIEW_WINDOW_OVERLAP": 409,
    "ERR_EMPLOYER_FEED_STALLED": 422,
    "ERR_NO_EMPLOYER_MATCH": 422,
    "ERR_LAYOUT_MAPPING_INCOMPLETE": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_BATCH_RECORD_COUNT_EXCEEDED": 422,
    "ERR_ESCROW_INSUFFICIENT": 402,
    "ERR_STALE_VERSION": 412,
    "ERR_DISCLOSURE_ALREADY_CURRENT": 409,
    "ERR_RESPONSE_ALREADY_MATERIALIZED": 409,
    "ERR_DISPUTE_RESPONSE_WINDOW_EXPIRED": 422,
    "ERR_BATCH_LAYOUT_NOT_VERIFIED": 422,
    "ERR_FEED_NOT_MONOTONIC": 422,
    "ERR_ACTIVE_FREEZE_BLOCK": 409,
    "ERR_REGULATORY_HOLD_IRRELEASABLE": 409,
    "ERR_COUNTER_FLOOR_VIOLATION": 409,
    "ERR_DISPUTE_TERMINAL": 409,
    "ERR_SETTLEMENT_OUTCOME_INVALID": 422,
}

ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The request is missing a recognized X-User-Role or X-User-ID header.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted by the endpoint's roles list.",
    "ERR_FORBIDDEN_OWNERSHIP": "The acting entity does not own the addressed resource.",
    "ERR_NOT_FOUND": "A path-addressed resource does not exist.",
    "ERR_REFERENCE_NOT_FOUND": "A foreign key supplied in the request body does not resolve to an existing row.",
    "ERR_INVALID_STATE": "The addressed resource is in a state from which the requested action is undefined.",
    "ERR_ALREADY_TERMINAL": "The addressed resource has already reached a terminal state.",
    "ERR_VERIFIER_RESTRICTED": "The requesting party's posture is not NORMAL or it is not authorized.",
    "ERR_WORKER_OPT_OUT": "The worker has opted out, so no verification may resolve the worker's data.",
    "ERR_PERMISSIBLE_PURPOSE_UNAVAILABLE": "The permissible purpose is unavailable: mismatched, revoked or expired.",
    "ERR_PRODUCT_NOT_PERMITTED_FOR_CLASS": "The product is not permitted for the requesting party's class, or is inactive.",
    "ERR_EMPLOYER_FROZEN": "The selected employer is frozen, blocking instant verification of its records.",
    "ERR_AUTHORIZATION_OVERLAP": "An authorization for the same worker, requesting party and purpose already covers the current instant.",
    "ERR_REVIEW_WINDOW_OVERLAP": "A currency review window is separated from an open review by fewer than three days.",
    "ERR_EMPLOYER_FEED_STALLED": "The selected employer's feed is stalled, so instant verification cannot be satisfied.",
    "ERR_NO_EMPLOYER_MATCH": "No candidate employer could be matched for the worker.",
    "ERR_LAYOUT_MAPPING_INCOMPLETE": "The layout's column map does not cover every required canonical field.",
    "ERR_DUPLICATE_RESOURCE": "A uniqueness constraint is violated.",
    "ERR_BATCH_RECORD_COUNT_EXCEEDED": "The batch's record count or a record's separation date is out of bounds.",
    "ERR_ESCROW_INSUFFICIENT": "The requesting party's escrow balance is below the fee this transaction would post.",
    "ERR_STALE_VERSION": "An expected version supplied in the body does not equal the resource's current version.",
    "ERR_DISCLOSURE_ALREADY_CURRENT": "The disclosure file may not be regenerated while the worker's disclosure state is CURRENT.",
    "ERR_RESPONSE_ALREADY_MATERIALIZED": "A response row already exists for this verification request.",
    "ERR_DISPUTE_RESPONSE_WINDOW_EXPIRED": "The employer's response arrived after the dispute response due date.",
    "ERR_BATCH_LAYOUT_NOT_VERIFIED": "The batch's record layout is not VERIFIED.",
    "ERR_FEED_NOT_MONOTONIC": "The batch's pay period end date is not strictly after the employer's last feed received date.",
    "ERR_ACTIVE_FREEZE_BLOCK": "A freeze is already ACTIVE for this employer.",
    "ERR_REGULATORY_HOLD_IRRELEASABLE": "A REGULATORY_HOLD freeze may not be released.",
    "ERR_COUNTER_FLOOR_VIOLATION": "A compensating adjustment would drive a conserved counter below zero.",
    "ERR_DISPUTE_TERMINAL": "A CLOSED dispute may not be reopened or responded to.",
    "ERR_SETTLEMENT_OUTCOME_INVALID": "The settlement names an invalid outcome or covers no ACCRUED accrual.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or ERROR_MESSAGES.get(error_id, error_id)