"""Error catalogue and the ApiError exception (PRD section 5)."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_CARE_MANAGER_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_CONTACT_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_CARE_PLAN_NOT_FOUND": 404,
    "ERR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_CONFERENCE_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_CRISIS_EPISODE_NOT_FOUND": 404,
    "ERR_TIME_ENTRY_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_STALE_CLIENT_VERSION": 412,
    "ERR_STALE_CARE_PLAN_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CLIENT_NOT_IN_SERVICE": 409,
    "ERR_ASSESSMENT_NOT_ACCEPTED": 409,
    "ERR_PINNED_ASSESSMENT_STALE": 409,
    "ERR_CARE_PLAN_NOT_ACTIVE": 409,
    "ERR_COVERAGE_CAPACITY_EXCEEDED": 409,
    "ERR_TIME_ENTRY_OVERLAP": 409,
    "ERR_TRAVEL_BUFFER_VIOLATION": 409,
    "ERR_INVOICE_PERIOD_OVERLAP": 409,
    "ERR_VENDOR_BARRED": 422,
    "ERR_COI_NOT_ACKNOWLEDGED": 422,
    "ERR_COI_ACK_BY_INELIGIBLE_PARTY": 422,
    "ERR_CAPACITY_BASIS_REQUIRED": 422,
    "ERR_SURROGATE_AUTHORITY_MISSING": 422,
    "ERR_QUORUM_NOT_MET": 422,
    "ERR_ESCALATION_PRECONDITION_UNMET": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_CRISIS_CONTEXT_REQUIRED": 422,
    "ERR_ENTITY_RELATIONSHIP_INVALID": 422,
    "ERR_DAILY_CAP_EXCEEDED": 422,
    "ERR_NO_BILLABLE_ACTIVITY": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_RETAINER_INSUFFICIENT": 402,
    "ERR_INTERNAL": 500,
    "ERR_NOT_FOUND": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or violates a declared constraint.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not reachable from the record's current state.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "Request rejected: %s." % error_id
        )
