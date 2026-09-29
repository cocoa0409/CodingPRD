"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication and authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_INVALID_DATE_RANGE": 422,
    # existence
    "ERR_SCHEME_NOT_FOUND": 404,
    "ERR_ASSESSOR_NOT_FOUND": 404,
    "ERR_QUALIFICATION_NOT_FOUND": 404,
    "ERR_DECLARATION_NOT_FOUND": 404,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_TEAM_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_WITNESS_SESSION_NOT_FOUND": 404,
    "ERR_NONCONFORMITY_NOT_FOUND": 404,
    "ERR_DECISION_NOT_FOUND": 404,
    "ERR_SCOPE_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_APPLICATION_VERSION": 412,
    "ERR_STALE_NONCONFORMITY_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_NONCONFORMITY_STATE_INVALID": 409,
    # impartiality, independence, segregation of duties
    "ERR_IMPARTIALITY_CONFLICT": 422,
    "ERR_ASSESSOR_IMPARTIALITY_RESTRICTED": 422,
    "ERR_PANEL_INDEPENDENCE_BREACH": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_APPEAL_REVIEWER_CONFLICT": 422,
    "ERR_NOT_ASSIGNED_TEAM_MEMBER": 422,
    # referential business rules
    "ERR_SCHEME_NOT_PUBLISHED": 422,
    "ERR_SCHEME_VERSION_SUPERSEDED": 422,
    "ERR_QUALIFICATION_NOT_GRANTED": 422,
    "ERR_SCOPE_NOT_ACTIVE": 422,
    "ERR_PLAN_NOT_APPROVED": 422,
    "ERR_SCOPE_LINE_NOT_REQUESTED": 422,
    # temporal business rules
    "ERR_ASSESSOR_SCHEDULE_CONFLICT": 409,
    "ERR_SITE_BUFFER_CONFLICT": 409,
    "ERR_NOT_YET_OVERDUE": 422,
    "ERR_RESPONSE_WINDOW_CLOSED": 422,
    "ERR_INVALID_NOTICE_PERIOD": 422,
    # constraint and capacity business rules
    "ERR_WITNESS_COVERAGE_INSUFFICIENT": 422,
    "ERR_PANEL_QUORUM_NOT_MET": 422,
    "ERR_ASSESSOR_CAPACITY_EXCEEDED": 422,
    "ERR_EFFECTIVENESS_EVIDENCE_INSUFFICIENT": 422,
    "ERR_DUPLICATE_PANEL_VOTE": 409,
    "ERR_DUPLICATE_ACTIVE_APPLICATION": 409,
    "ERR_CONDITIONS_REQUIRE_REDUCED_SCOPE": 422,
    "ERR_UNANNOUNCED_NOT_AUTHORIZED": 422,
    "ERR_REMOTE_WITNESS_NOT_PERMITTED": 422,
    "ERR_MRA_ESCALATION_NOT_ELIGIBLE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required",
    "ERR_ROLE_NOT_PERMITTED": "the acting role may not perform this operation",
    "ERR_NOT_RESOURCE_OWNER": "the acting organization does not own this resource",
    "ERR_INVALID_REQUEST": "the request body is invalid",
    "ERR_INVALID_PAGINATION": "limit must be an integer in 1..100 and offset an integer of at least 0",
    "ERR_INVALID_DATE_RANGE": "the supplied date range is not coherent",
}


class ApiError(Exception):
    """Raised anywhere in a request to abort with a catalogue error."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id) or _humanize(error_id)


def _humanize(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower()
