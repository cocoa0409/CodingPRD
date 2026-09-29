"""Error catalogue for the Extended School Year & Compensatory Services API.

Every error_id / HTTP status pair below is taken verbatim from PRD.md section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # ------------------------------------------------------------ auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_STUDENT_GUARDIAN": 403,
    "ERR_NOT_ASSIGNED_PROVIDER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # ------------------------------------------------------- not found
    "ERR_STUDENT_NOT_FOUND": 404,
    "ERR_DETERMINATION_NOT_FOUND": 404,
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_PROVIDER_NOT_FOUND": 404,
    "ERR_COMMITMENT_NOT_FOUND": 404,
    "ERR_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_RUN_NOT_FOUND": 404,
    "ERR_SERVICE_LOG_NOT_FOUND": 404,
    "ERR_AWARD_NOT_FOUND": 404,
    "ERR_MAKEUP_SESSION_NOT_FOUND": 404,
    "ERR_FUND_ALLOCATION_NOT_FOUND": 404,
    "ERR_DUE_PROCESS_RECORD_NOT_FOUND": 404,
    # ---------------------------------------------------- request shape
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    # --------------------------------------------- state and concurrency
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_COMMITMENT_VERSION": 412,
    "ERR_STALE_AWARD_VERSION": 412,
    # ----------------------------------------- safety and referential
    "ERR_STAY_PUT_BLOCKED": 409,
    "ERR_PROVIDER_CREDENTIAL_EXPIRED": 422,
    "ERR_PROVIDER_NOT_ACTIVE": 422,
    "ERR_PROVIDER_ROLE_MISMATCH": 422,
    # ------------------------------------------------------- temporal
    "ERR_PROVIDER_TIME_CONFLICT": 409,
    "ERR_RUN_WINDOW_OVERLAP": 409,
    "ERR_ROUTE_TURNAROUND_VIOLATION": 422,
    "ERR_MAKEUP_OUTSIDE_WINDOW": 422,
    "ERR_NOT_INSTRUCTIONAL_DATE": 422,
    # ----------------------------------------------------- constraint
    "ERR_STUDENT_NOT_ESY_ELIGIBLE": 422,
    "ERR_NO_INSTRUCTIONAL_DAYS": 422,
    "ERR_DAILY_MINUTES_CAP_EXCEEDED": 422,
    "ERR_INSUFFICIENT_PROBE_DATA": 422,
    "ERR_NO_COMPENSABLE_MINUTES": 422,
    "ERR_PROPOSAL_OUT_OF_RANGE": 422,
    "ERR_OVERBOOKED_MAKEUP_MINUTES": 422,
    "ERR_DUPLICATE_SERVICE_LOG": 409,
    "ERR_DUPLICATE_BUDGET_CODE": 409,
    "ERR_DUPLICATE_AWARD": 409,
    "ERR_PROVIDER_CAPACITY_EXCEEDED": 422,
    "ERR_RUN_CAPACITY_EXCEEDED": 422,
    # --------------------------------------------------------- fiscal
    "ERR_FUND_FROZEN": 409,
    "ERR_NO_FUND_WITH_CAPACITY": 422,
    "ERR_FUND_INDIRECT_OVERAGE": 422,
    "ERR_SUPPLANT_RESTRICTION": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_STUDENT_GUARDIAN": "The acting guardian does not own the addressed record.",
    "ERR_NOT_ASSIGNED_PROVIDER": "The acting provider is not assigned to the addressed record.",
    "ERR_SEGREGATION_OF_DUTIES": "The approving user may not be the user who produced the artifact.",
    "ERR_INVALID_REQUEST": "The request body is not structurally valid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in [1, 100] and offset an integer >= 0.",
    "ERR_INVALID_STATE": "The requested transition does not exist from the current state.",
    "ERR_STALE_COMMITMENT_VERSION": "expected_commitment_version does not match the commitment's current version.",
    "ERR_STALE_AWARD_VERSION": "expected_award_version does not match the award's current version.",
    "ERR_STAY_PUT_BLOCKED": "The student is under stay-put protection.",
    "ERR_PROVIDER_CREDENTIAL_EXPIRED": "The provider's credential expires before the last covered date.",
    "ERR_PROVIDER_NOT_ACTIVE": "The provider's status is not ACTIVE.",
    "ERR_PROVIDER_ROLE_MISMATCH": "The provider's role_type is not permitted for this service_type.",
    "ERR_PROVIDER_TIME_CONFLICT": "The provider already holds an overlapping active assignment.",
    "ERR_RUN_WINDOW_OVERLAP": "Another scheduled run of this route occupies an overlapping window.",
    "ERR_ROUTE_TURNAROUND_VIOLATION": "Consecutive runs of this route leave less than the required turnaround gap.",
    "ERR_MAKEUP_OUTSIDE_WINDOW": "The session_date falls outside the award's delivery window.",
    "ERR_NOT_INSTRUCTIONAL_DATE": "The supplied service_date is not an instructional date of the program.",
    "ERR_STUDENT_NOT_ESY_ELIGIBLE": "The student's esy_eligibility_status is not ELIGIBLE.",
    "ERR_NO_INSTRUCTIONAL_DAYS": "The program calendar yields no instructional day.",
    "ERR_DAILY_MINUTES_CAP_EXCEEDED": "The heaviest single-week daily load exceeds the program's daily_minutes_cap.",
    "ERR_INSUFFICIENT_PROBE_DATA": "The determination carries fewer than the minimum probe domains.",
    "ERR_NO_COMPENSABLE_MINUTES": "The computed award falls below the minimum awardable minutes.",
    "ERR_PROPOSAL_OUT_OF_RANGE": "The minute figure falls outside the permitted proposal band.",
    "ERR_OVERBOOKED_MAKEUP_MINUTES": "Booking this session would overbook the award.",
    "ERR_DUPLICATE_SERVICE_LOG": "A VERIFIED service log already covers this commitment and service_date.",
    "ERR_DUPLICATE_BUDGET_CODE": "The program_id and budget_code pair already exists.",
    "ERR_DUPLICATE_AWARD": "A non-terminal award already exists for this student and source program.",
    "ERR_PROVIDER_CAPACITY_EXCEEDED": "The provider's aggregate weekly load exceeds max_weekly_minutes.",
    "ERR_RUN_CAPACITY_EXCEEDED": "The transportation run has no free seat.",
    "ERR_FUND_FROZEN": "No fund allocation of the program is OPEN.",
    "ERR_NO_FUND_WITH_CAPACITY": "No OPEN allocation can absorb the base cost.",
    "ERR_FUND_INDIRECT_OVERAGE": "The selected allocation cannot absorb the indirect cost.",
    "ERR_SUPPLANT_RESTRICTION": "The compensatory charge exceeds the federal compensatory cap.",
}
