"""Error catalogue for the ESOP Administration API.

Every error_id and its HTTP status comes verbatim from PRD section 5 /
SCAFFOLD 1.6.  Nothing here is invented.
"""

ERROR_HTTP_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_PARTICIPANT_NOT_FOUND": 404,
    "ERR_VALUATION_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_LOAN_PAYMENT_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_FORFEITURE_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_INSTALLMENT_NOT_FOUND": 404,
    "ERR_EXERCISE_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_PLAN_FROZEN": 409,
    "ERR_PLAN_STATE_INVALID": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_PLAN_VERSION": 412,
    "ERR_NO_APPROVED_VALUATION": 409,
    "ERR_ENTITY_MISMATCH": 409,
    "ERR_CHALLENGE_ROUNDS_EXHAUSTED": 409,
    "ERR_VALUATION_PERIOD_OVERLAP": 409,
    "ERR_PUT_WINDOW_BUFFER_VIOLATION": 409,
    "ERR_PUT_WINDOW_CLOSED": 422,
    "ERR_INSTALLMENT_NOT_DUE": 422,
    "ERR_DIVERSIFICATION_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_EMPLOYEE_NUMBER": 409,
    "ERR_ELECTION_NOT_PERMITTED": 422,
    "ERR_RETIREMENT_AGE_NOT_ATTAINED": 422,
    "ERR_NO_ELIGIBLE_PARTICIPANTS": 422,
    "ERR_INSUFFICIENT_SHARES": 422,
    "ERR_DIVERSIFICATION_LIMIT_EXCEEDED": 422,
    "ERR_FORFEITURE_SWEEP_REQUIRED": 409,
    "ERR_ANNUAL_ADDITIONS_EXCEEDED": 422,
    "ERR_PAYMENT_EXCEEDS_BALANCE": 422,
    "ERR_INSUFFICIENT_REPURCHASE_RESERVE": 402,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or name an undeclared role.",
    "ERR_FORBIDDEN_ROLE": "The authenticated role may not call this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "A participant may only act on their own resources.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user may not both propose and bless this act.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_PLAN_NOT_FOUND": "No ESOP plan matches the supplied identifier.",
    "ERR_PARTICIPANT_NOT_FOUND": "No participant matches the supplied identifier.",
    "ERR_VALUATION_NOT_FOUND": "No valuation matches the supplied identifier.",
    "ERR_LOAN_NOT_FOUND": "No ESOP loan matches the supplied identifier.",
    "ERR_LOAN_PAYMENT_NOT_FOUND": "No loan payment matches the supplied identifier.",
    "ERR_RUN_NOT_FOUND": "No allocation run matches the supplied identifier.",
    "ERR_ALLOCATION_NOT_FOUND": "No share allocation matches the supplied identifier.",
    "ERR_FORFEITURE_NOT_FOUND": "No forfeiture event matches the supplied identifier.",
    "ERR_ELECTION_NOT_FOUND": "No distribution election matches the supplied identifier.",
    "ERR_INSTALLMENT_NOT_FOUND": "No installment payment matches the supplied identifier.",
    "ERR_EXERCISE_NOT_FOUND": "No put option exercise matches the supplied identifier.",
    "ERR_STATEMENT_NOT_FOUND": "No participant statement matches the supplied identifier.",
    "ERR_PLAN_FROZEN": "The governing plan is frozen; every mutating operation is refused.",
    "ERR_PLAN_STATE_INVALID": "The plan is not in the posture this operation requires.",
    "ERR_INVALID_STATE": "The target resource is not in a state from which this transition is declared.",
    "ERR_STALE_PLAN_VERSION": "expected_plan_version does not match the plan's current version.",
    "ERR_NO_APPROVED_VALUATION": "No approved valuation stands behind this operation.",
    "ERR_ENTITY_MISMATCH": "The run and its valuation are not coherent.",
    "ERR_CHALLENGE_ROUNDS_EXHAUSTED": "This appraisal has exhausted its challenge rounds.",
    "ERR_VALUATION_PERIOD_OVERLAP": "The coverage interval overlaps another open appraisal.",
    "ERR_PUT_WINDOW_BUFFER_VIOLATION": "The put option window cooling buffer has not elapsed.",
    "ERR_PUT_WINDOW_CLOSED": "The put option window is not open on the logical clock date.",
    "ERR_INSTALLMENT_NOT_DUE": "The installment is not yet due or an earlier installment is unpaid.",
    "ERR_DIVERSIFICATION_WINDOW_CLOSED": "The plan year lies outside the qualified election period.",
    "ERR_DUPLICATE_EMPLOYEE_NUMBER": "Another participant of this plan already carries this employee number.",
    "ERR_ELECTION_NOT_PERMITTED": "The participant's status does not permit this election type.",
    "ERR_RETIREMENT_AGE_NOT_ATTAINED": "The participant has not reached the plan's normal retirement age.",
    "ERR_NO_ELIGIBLE_PARTICIPANTS": "No eligible participant stands behind this allocation run.",
    "ERR_INSUFFICIENT_SHARES": "Not enough shares stand behind the request.",
    "ERR_DIVERSIFICATION_LIMIT_EXCEEDED": "The cumulative diversification cap would be breached.",
    "ERR_FORFEITURE_SWEEP_REQUIRED": "Forfeited shares are awaiting reallocation.",
    "ERR_ANNUAL_ADDITIONS_EXCEEDED": "The annual additions ceiling leaves a residue under a reduce-contribution policy.",
    "ERR_PAYMENT_EXCEEDS_BALANCE": "The payment exceeds the loan's remaining balance.",
    "ERR_INSUFFICIENT_REPURCHASE_RESERVE": "The repurchase reserve does not cover this exercise.",
}


class ApiError(Exception):
    """A refusal carrying the catalogue's error_id and HTTP status."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
