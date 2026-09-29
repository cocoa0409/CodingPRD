"""The complete error catalogue (69 identifiers) with its HTTP status mapping.

PRD 2.3: an error response carries `data.error_id` and `data.message`; the
`error_id` is the contract, the message is human-facing only.
"""

HTTP_STATUS = {
    # --- authentication / authorisation -----------------------------------
    "ERR_MISSING_USER_ID": 401,
    "ERR_UNKNOWN_USER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FOREIGN_RESOURCE": 403,
    # --- request shape -----------------------------------------------------
    "ERR_VALIDATION": 400,
    # --- existence ---------------------------------------------------------
    "ERR_CEDENT_NOT_FOUND": 404,
    "ERR_REINSURER_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_PRIOR_PROGRAM_NOT_FOUND": 404,
    "ERR_EXPOSURE_SUBMISSION_NOT_FOUND": 404,
    "ERR_LAYER_NOT_FOUND": 404,
    "ERR_MARKET_SUBMISSION_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_SIGNING_LINE_NOT_FOUND": 404,
    "ERR_DISCLOSURE_NOT_FOUND": 404,
    "ERR_TRANSACTION_NOT_FOUND": 404,
    "ERR_CLAIM_ADVOCACY_NOT_FOUND": 404,
    "ERR_CESSION_DISPUTE_NOT_FOUND": 404,
    # --- own-state / cross-entity state ------------------------------------
    "ERR_PROGRAM_STATE_INVALID": 409,
    "ERR_DOCUMENT_SEQUENCE_INVALID": 409,
    "ERR_SUBMISSION_STATE_INVALID": 409,
    "ERR_LAYER_STATE_INVALID": 409,
    "ERR_MARKET_SUBMISSION_CLOSED": 409,
    "ERR_QUOTE_STATE_INVALID": 409,
    "ERR_SIGNING_LINE_STATE_INVALID": 409,
    "ERR_DISCLOSURE_STATE_INVALID": 409,
    "ERR_TRANSACTION_STATE_INVALID": 409,
    "ERR_ADVOCACY_STATE_INVALID": 409,
    "ERR_DISPUTE_STATE_INVALID": 409,
    "ERR_LAYER_NOT_BOUND": 409,
    "ERR_DOCUMENTATION_NOT_AGREED": 409,
    # --- optimistic concurrency -------------------------------------------
    "ERR_STALE_LAYER_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
    # --- safety / governance ----------------------------------------------
    "ERR_MARKET_SUSPENDED": 422,
    "ERR_LEAD_NOT_AUTHORISED": 422,
    "ERR_CEDENT_SUSPENDED": 422,
    "ERR_SIGNOFF_SCORE_TOO_LOW": 422,
    "ERR_DISCLOSURE_NOT_ACKNOWLEDGED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    # --- temporal ----------------------------------------------------------
    "ERR_TREATY_PERIOD_INVALID": 422,
    "ERR_DEADLINE_NOT_IN_FUTURE": 422,
    "ERR_RESPONSE_DEADLINE_PASSED": 422,
    "ERR_QUOTE_EXPIRED": 422,
    "ERR_EVENT_DATE_OUT_OF_PERIOD": 422,
    "ERR_CERTAINTY_NOT_BREACHED": 422,
    # --- uniqueness --------------------------------------------------------
    "ERR_DUPLICATE_NAME": 409,
    "ERR_OVERLAPPING_TREATY_PERIOD": 409,
    "ERR_DUPLICATE_MARKET_SUBMISSION": 409,
    "ERR_DUPLICATE_CLAIM_REFERENCE": 409,
    "ERR_ALREADY_REVERSED": 409,
    "ERR_PROGRAM_HAS_OPEN_TRANSACTIONS": 409,
    # --- structural / relational ------------------------------------------
    "ERR_RENEWAL_PRIOR_MISMATCH": 422,
    "ERR_LAYER_STRUCTURE_INVALID": 422,
    "ERR_SUBLIMIT_EXCEEDS_LIMIT": 422,
    "ERR_LINE_EXCEEDS_OFFER": 422,
    "ERR_LINE_EXCEEDS_MAX_LINE": 422,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_LAYER_NOT_OVERSUBSCRIBED": 422,
    "ERR_LEAD_LINE_MISSING": 422,
    "ERR_DISCLOSURE_PCT_MISMATCH": 422,
    "ERR_TRANSACTION_TYPE_LINK_INVALID": 422,
    "ERR_LINE_LAYER_MISMATCH": 422,
    "ERR_RESOLUTION_AMOUNT_INVALID": 422,
    "ERR_COLLECTION_BLOCKED_BY_ARBITRATION": 422,
    # --- fiscal capacity ---------------------------------------------------
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_AGGREGATE_LIMIT_EXHAUSTED": 422,
    "ERR_DISPUTE_EXCEEDS_CESSION": 422,
    "ERR_COLLECTION_EXCEEDS_COLLECTIBLE": 422,
    "ERR_INSUFFICIENT_FIDUCIARY_BALANCE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# Convenience wrappers used pervasively by the routes -----------------------

def bad_request(message):
    raise ApiError("ERR_VALIDATION", message)
