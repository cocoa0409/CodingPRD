"""Error catalog (PRD section 5 / scaffold 1.6)."""

ERROR_HTTP = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ROLE_IDENTITY_MISMATCH": 403,
    # request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    # existence
    "ERR_ISSUER_NOT_FOUND": 404,
    "ERR_FIRM_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_TRANCHE_NOT_FOUND": 404,
    "ERR_ENHANCEMENT_NOT_FOUND": 404,
    "ERR_OFFICIAL_STATEMENT_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_UNDERTAKING_NOT_FOUND": 404,
    "ERR_RATING_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_PRESENTATION_NOT_FOUND": 404,
    "ERR_ORDER_PERIOD_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_CLOSING_DOCUMENT_NOT_FOUND": 404,
    # referential integrity
    "ERR_CROSS_DEAL_REFERENCE": 422,
    # optimistic concurrency
    "ERR_STALE_DEAL_VERSION": 412,
    "ERR_STALE_ORDER_PERIOD_VERSION": 412,
    # state legality
    "ERR_DEAL_INVALID_STATE": 409,
    "ERR_OS_INVALID_STATE": 409,
    "ERR_SECTION_INVALID_STATE": 409,
    "ERR_UNDERTAKING_INVALID_STATE": 409,
    "ERR_ENHANCEMENT_INVALID_STATE": 409,
    "ERR_RATING_ENGAGEMENT_INVALID_STATE": 409,
    "ERR_PRESENTATION_INVALID_STATE": 409,
    "ERR_ORDER_PERIOD_INVALID_STATE": 409,
    "ERR_ORDER_INVALID_STATE": 409,
    "ERR_CLOSING_DOC_ALREADY_EXECUTED": 409,
    # MSRB conduct
    "ERR_MA_UNDERWRITER_CONFLICT": 422,
    "ERR_FIRM_SUSPENDED": 422,
    "ERR_MA_ENGAGEMENT_REQUIRED": 422,
    "ERR_SENIOR_MANAGER_REQUIRED": 422,
    "ERR_SALE_METHOD_CONFLICT": 422,
    "ERR_SECTION_SELF_APPROVAL": 422,
    "ERR_SIGNATORY_ROLE_INVALID": 422,
    # disclosure adequacy
    "ERR_MANDATORY_SECTION_NOT_APPROVED": 422,
    "ERR_DISCLOSURE_RISK_SECTION_REQUIRED": 422,
    "ERR_UNDERTAKING_NOT_ACTIVE": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_OS_NOT_FINAL_POSTED": 422,
    "ERR_PRESENTATION_REQUIRED": 422,
    "ERR_DISCLOSURE_NOT_CLEARED": 422,
    "ERR_PRICING_PRECONDITION_UNMET": 422,
    # temporal
    "ERR_ORDER_PERIOD_OVERLAP": 422,
    "ERR_PRESENTATION_BUFFER_CONFLICT": 422,
    "ERR_ORDER_PERIOD_WINDOW_CLOSED": 422,
    "ERR_MATURITY_DATE_UNALIGNED": 422,
    # structural
    "ERR_CALL_FEATURE_INVALID": 422,
    "ERR_DENOMINATION_INVALID": 422,
    "ERR_PAR_SCHEDULE_MISMATCH": 422,
    "ERR_TRANCHE_SEQUENCE_CONFLICT": 422,
    "ERR_DUPLICATE_SYNDICATE_MEMBER": 422,
    "ERR_DUPLICATE_RATING_ENGAGEMENT": 422,
    "ERR_REFUNDED_TRANCHE_INVALID": 422,
    "ERR_ORDER_TYPE_NOT_PERMITTED": 422,
    "ERR_DUPLICATE_MSRB_REGISTRATION": 422,
    "ERR_DUPLICATE_SERIES_DESIGNATION": 422,
    # fiscal
    "ERR_LIABILITY_PCT_SUM_INVALID": 422,
    "ERR_COMPENSATION_INPUT_MISSING": 422,
    "ERR_PREMIUM_EXCEEDS_PROCEEDS": 422,
    "ERR_ENHANCEMENT_ALREADY_COMMITTED": 422,
    "ERR_CLOSING_DOCS_INCOMPLETE": 422,
    "ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE": 422,
    # generic transport-level fallbacks (never part of the declared catalog)
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or blank.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_ROLE_IDENTITY_MISMATCH": "The acting principal does not resolve to a compatible identity.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are invalid.",
    "ERR_CROSS_DEAL_REFERENCE": "A referenced entity belongs to a different deal.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 422)
        if message is None:
            message = DEFAULT_MESSAGES.get(
                error_id, error_id.replace("ERR_", "").replace("_", " ").lower() + "."
            )
        self.message = message


def fail(error_id, message=None):
    raise ApiError(error_id, message)
