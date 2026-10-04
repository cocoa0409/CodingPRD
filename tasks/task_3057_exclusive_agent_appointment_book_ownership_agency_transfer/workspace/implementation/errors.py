"""Error identifiers, HTTP statuses and the API exception type.

The catalogue mirrors PRD section 5 / SCAFFOLD §1.6 exactly.  Every error the
server can raise is declared here so that no route invents an identifier.
"""

ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_AGENCY_NOT_FOUND = "ERR_AGENCY_NOT_FOUND"
ERR_AGENT_NOT_FOUND = "ERR_AGENT_NOT_FOUND"
ERR_AGREEMENT_NOT_FOUND = "ERR_AGREEMENT_NOT_FOUND"
ERR_POLICY_NOT_FOUND = "ERR_POLICY_NOT_FOUND"
ERR_CLAIM_NOT_FOUND = "ERR_CLAIM_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_LICENSED_REQUIRED = "ERR_LICENSED_REQUIRED"
ERR_SPONSOR_AGREEMENT_NOT_ACTIVE = "ERR_SPONSOR_AGREEMENT_NOT_ACTIVE"
ERR_MARKET_NEED_EXISTS = "ERR_MARKET_NEED_EXISTS"
ERR_AGENCY_STAFFING_CAP = "ERR_AGENCY_STAFFING_CAP"
ERR_SCHEDULE_MISSING = "ERR_SCHEDULE_MISSING"
ERR_INTERVAL_OVERLAP = "ERR_INTERVAL_OVERLAP"
ERR_ALLOWANCE_INSUFFICIENT = "ERR_ALLOWANCE_INSUFFICIENT"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_HOLDING_POLICIES_REMAIN = "ERR_HOLDING_POLICIES_REMAIN"
ERR_NO_SUCCESSOR_AGENT = "ERR_NO_SUCCESSOR_AGENT"
ERR_DUPLICATE_POLICY = "ERR_DUPLICATE_POLICY"
ERR_INVALID_TERRITORY = "ERR_INVALID_TERRITORY"
ERR_STAFF_NOT_FOUND = "ERR_STAFF_NOT_FOUND"

MESSAGES = {
    ERR_UNAUTHENTICATED: "X-User-Role or X-User-ID header missing or empty.",
    ERR_UNAUTHORIZED: "The acting role is not permitted for this operation.",
    ERR_AGENCY_NOT_FOUND: "No agency matches the id in the path.",
    ERR_AGENT_NOT_FOUND: "No agent matches the id in the path.",
    ERR_AGREEMENT_NOT_FOUND: "No agreement matches the id in the path.",
    ERR_POLICY_NOT_FOUND: "No policy matches the id in the path.",
    ERR_CLAIM_NOT_FOUND: "No claim matches the id in the path.",
    ERR_INVALID_STATE: "The target resource is not in the state required by the transition.",
    ERR_ALREADY_TERMINAL: "A transition was attempted from a terminal state.",
    ERR_LICENSED_REQUIRED: "The acting agent's license is not LICENSED or has expired.",
    ERR_SPONSOR_AGREEMENT_NOT_ACTIVE: "The sponsoring agreement's owner agent is not in a live state.",
    ERR_MARKET_NEED_EXISTS: "The market-need score is too low for the requested territory.",
    ERR_AGENCY_STAFFING_CAP: "The target agency already carries twelve agency-level units.",
    ERR_SCHEDULE_MISSING: "The commission schedule is missing a required product line.",
    ERR_INTERVAL_OVERLAP: "The requested interval collides with a sibling interval.",
    ERR_ALLOWANCE_INSUFFICIENT: "The allowance pool remaining is less than the campaign draw.",
    ERR_STALE_VERSION: "expected parent version does not match the current parent version.",
    ERR_HOLDING_POLICIES_REMAIN: "The previous agent still holds at least one OPEN policy.",
    ERR_NO_SUCCESSOR_AGENT: "No same-region ACTIVE agent is available as a successor.",
    ERR_DUPLICATE_POLICY: "policy_number or agency_code is already in use.",
    ERR_INVALID_TERRITORY: "The address belongs to a territory that cannot fit the appointment.",
    ERR_STAFF_NOT_FOUND: "No team member matches the id in the path.",
}

HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_AGENCY_NOT_FOUND: 404,
    ERR_AGENT_NOT_FOUND: 404,
    ERR_AGREEMENT_NOT_FOUND: 404,
    ERR_POLICY_NOT_FOUND: 404,
    ERR_CLAIM_NOT_FOUND: 404,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_LICENSED_REQUIRED: 400,
    ERR_SPONSOR_AGREEMENT_NOT_ACTIVE: 409,
    ERR_MARKET_NEED_EXISTS: 409,
    ERR_AGENCY_STAFFING_CAP: 409,
    ERR_SCHEDULE_MISSING: 400,
    ERR_INTERVAL_OVERLAP: 409,
    ERR_ALLOWANCE_INSUFFICIENT: 400,
    ERR_STALE_VERSION: 412,
    ERR_HOLDING_POLICIES_REMAIN: 409,
    ERR_NO_SUCCESSOR_AGENT: 409,
    ERR_DUPLICATE_POLICY: 409,
    ERR_INVALID_TERRITORY: 400,
    ERR_STAFF_NOT_FOUND: 404,
}


class ApiError(Exception):
    """Carries the error_id, the human message and the HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or HTTP_STATUS.get(error_id, 400)
        super().__init__(self.message)