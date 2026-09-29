"""Error catalogue for the LTCH Admission & Length-of-Stay Compliance API.

Every error id and HTTP status is taken verbatim from PRD.md section 5.
"""

ERROR_HTTP_STATUS = {
    # request / auth
    "ERR_VALIDATION": 400,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not found
    "ERR_HOSPITAL_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_PHYSICIAN_NOT_FOUND": 404,
    "ERR_DRG_RATE_NOT_FOUND": 404,
    "ERR_CRITERIA_SET_NOT_FOUND": 404,
    "ERR_PERIOD_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_STAY_NOT_FOUND": 404,
    "ERR_WEANING_PLAN_NOT_FOUND": 404,
    "ERR_INTERRUPTION_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_REVIEW_NOT_FOUND": 404,
    "ERR_QUERY_NOT_FOUND": 404,
    # concurrency
    "ERR_STALE_STAY_VERSION": 412,
    "ERR_STALE_PATIENT_VERSION": 412,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_PERIOD_CLOSED": 409,
    "ERR_NO_OPEN_PERIOD": 422,
    # screening / admission
    "ERR_NO_EFFECTIVE_CRITERIA_SET": 422,
    "ERR_REFERRAL_NOT_ELIGIBLE": 422,
    "ERR_CRITERIA_SET_SUPERSEDED": 422,
    "ERR_PATIENT_ALREADY_ADMITTED": 409,
    "ERR_PATIENT_STAY_OVERLAP": 422,
    "ERR_REFERRAL_SOURCE_BREACHED": 422,
    "ERR_ADMISSION_BEFORE_ACUTE_DISCHARGE": 422,
    "ERR_ADMISSION_IN_FUTURE": 422,
    # interruptions / recombination
    "ERR_INTERRUPTION_BEFORE_ADMISSION": 422,
    "ERR_INTERRUPTION_BUFFER_VIOLATION": 422,
    "ERR_INTERRUPTION_LIMIT_EXCEEDED": 422,
    "ERR_RECOMBINATION_WINDOW_EXCEEDED": 422,
    # weaning / documentation
    "ERR_WEANING_PLAN_EXISTS": 409,
    "ERR_WEANING_PROGRESSION_INSUFFICIENT": 422,
    "ERR_INSUFFICIENT_SBT_ATTEMPTS": 422,
    "ERR_PHYSICIAN_NOT_CREDENTIALED": 422,
    "ERR_IDT_DOCUMENTATION_STALE": 422,
    "ERR_WEANING_PLAN_OPEN": 422,
    "ERR_QUERY_RESPONSE_WINDOW_EXPIRED": 422,
    # pricing / ledger
    "ERR_DETERMINATION_EXISTS": 409,
    "ERR_REVIEW_NOT_RESOLVED": 422,
    "ERR_OPEN_QUERIES_BLOCK_FINALIZE": 422,
    "ERR_PERIOD_HAS_DRAFT_DETERMINATIONS": 422,
    "ERR_PERIOD_LEDGER_MISMATCH": 409,
    # reference data
    "ERR_DUPLICATE_KEY": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogue error."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_HTTP_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."
