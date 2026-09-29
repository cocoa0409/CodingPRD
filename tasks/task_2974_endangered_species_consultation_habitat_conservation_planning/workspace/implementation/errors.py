"""Error catalogue (PRD section 5) and the exception used to signal it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


HTTP_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ADJUDICATOR_CONFLICT": 403,
    "ERR_SPECIES_NOT_FOUND": 404,
    "ERR_PROPONENT_NOT_FOUND": 404,
    "ERR_PROJECT_ACTION_NOT_FOUND": 404,
    "ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND": 404,
    "ERR_PRESENCE_DETERMINATION_NOT_FOUND": 404,
    "ERR_CONSULTATION_NOT_FOUND": 404,
    "ERR_HCP_NOT_FOUND": 404,
    "ERR_CONSERVATION_BANK_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_MONITORING_REPORT_NOT_FOUND": 404,
    "ERR_CIRCUMSTANCE_EVENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_PERMIT_NOT_ACTIVE": 409,
    "ERR_SURVEY_WINDOW_CONFLICT": 409,
    "ERR_REPORTING_PERIOD_OVERLAP": 409,
    "ERR_INSUFFICIENT_BANK_CREDITS": 409,
    "ERR_STALE_HCP_VERSION": 412,
    "ERR_STALE_PERMIT_VERSION": 412,
    "ERR_SPECIES_NOT_LISTED": 422,
    "ERR_CONSULTATION_TYPE_MISMATCH": 422,
    "ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION": 422,
    "ERR_JEOPARDY_UNRESOLVED": 422,
    "ERR_SURVEY_WINDOW_INVALID": 422,
    "ERR_CONSULTATION_DEADLINE_PASSED": 422,
    "ERR_PERIOD_OUTSIDE_PERMIT_TERM": 422,
    "ERR_NO_PRESENCE_DETERMINATIONS": 422,
    "ERR_NO_MITIGATION_COMMITMENTS": 422,
    "ERR_BANK_NOT_ELIGIBLE": 422,
    "ERR_FUNDING_NOT_ASSURED": 422,
    "ERR_MITIGATION_SHORTFALL": 422,
    "ERR_TAKE_LIMIT_EXCEEDED": 422,
    "ERR_RESERVE_CONTRIBUTION_INSUFFICIENT": 422,
}

DEFAULT_MESSAGE = {
    "ERR_INVALID_REQUEST": "The request body or query string is not valid.",
    "ERR_UNAUTHENTICATED": "The caller could not be authenticated.",
    "ERR_ROLE_NOT_PERMITTED": "This role is not permitted on this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": (
        "The official who approved the plan may not issue its permit."),
    "ERR_ADJUDICATOR_CONFLICT": (
        "The official who issued the permit may not adjudicate its reports."),
    "ERR_SPECIES_NOT_FOUND": "No such species.",
    "ERR_PROPONENT_NOT_FOUND": "No such proponent.",
    "ERR_PROJECT_ACTION_NOT_FOUND": "No such project action.",
    "ERR_CRITICAL_HABITAT_UNIT_NOT_FOUND": "No such critical habitat unit.",
    "ERR_PRESENCE_DETERMINATION_NOT_FOUND": "No such presence determination.",
    "ERR_CONSULTATION_NOT_FOUND": "No such consultation.",
    "ERR_HCP_NOT_FOUND": "No such habitat conservation plan.",
    "ERR_CONSERVATION_BANK_NOT_FOUND": "No such conservation bank.",
    "ERR_PERMIT_NOT_FOUND": "No such incidental take permit.",
    "ERR_MONITORING_REPORT_NOT_FOUND": "No such monitoring report.",
    "ERR_CIRCUMSTANCE_EVENT_NOT_FOUND": "No such changed circumstance event.",
    "ERR_INVALID_STATE_TRANSITION": (
        "The resource is not in a legal source state for this transition."),
    "ERR_PERMIT_NOT_ACTIVE": "The incidental take permit is not ACTIVE.",
    "ERR_SURVEY_WINDOW_CONFLICT": (
        "The survey window conflicts with an existing survey on this unit."),
    "ERR_REPORTING_PERIOD_OVERLAP": (
        "The reporting period overlaps an existing report on this permit."),
    "ERR_INSUFFICIENT_BANK_CREDITS": "The bank has insufficient credits.",
    "ERR_STALE_HCP_VERSION": "The supplied plan version is stale.",
    "ERR_STALE_PERMIT_VERSION": "The supplied permit version is stale.",
    "ERR_SPECIES_NOT_LISTED": (
        "A conservation bank requires an ENDANGERED or THREATENED species."),
    "ERR_CONSULTATION_TYPE_MISMATCH": (
        "The consultation type does not match this concluding action."),
    "ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION": (
        "A habitat conservation plan requires a NON_FEDERAL action."),
    "ERR_JEOPARDY_UNRESOLVED": (
        "An unresolved JEOPARDY opinion blocks plan approval."),
    "ERR_SURVEY_WINDOW_INVALID": "The survey window is not coherent.",
    "ERR_CONSULTATION_DEADLINE_PASSED": (
        "The consultation deadline has already passed."),
    "ERR_PERIOD_OUTSIDE_PERMIT_TERM": (
        "The reporting period lies outside the permit term."),
    "ERR_NO_PRESENCE_DETERMINATIONS": (
        "The action has no usable presence determinations."),
    "ERR_NO_MITIGATION_COMMITMENTS": (
        "The plan has no reserved mitigation commitments."),
    "ERR_BANK_NOT_ELIGIBLE": "The conservation bank is not eligible.",
    "ERR_FUNDING_NOT_ASSURED": "The plan funding is not fully assured.",
    "ERR_MITIGATION_SHORTFALL": (
        "Secured mitigation falls short of the final requirement."),
    "ERR_TAKE_LIMIT_EXCEEDED": (
        "The reported take exceeds the permit's remaining take."),
    "ERR_RESERVE_CONTRIBUTION_INSUFFICIENT": (
        "The contribution does not cover the required additional amount."),
}
