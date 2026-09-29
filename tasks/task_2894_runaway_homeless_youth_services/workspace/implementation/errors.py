"""Error catalogue and the ApiError exception.

Every entry traces to PRD section 5 (Error Code Catalogue).  The HTTP status of
each identifier is the one declared there; nothing is inferred.
"""

ERROR_STATUS = {
    # auth / rbac / ownership / segregation
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_VOTE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # not-found (the eleven codes of PRD 2.10)
    "ERR_PROGRAM_NOT_FOUND": 404,
    "ERR_YOUTH_NOT_FOUND": 404,
    "ERR_ADMISSION_NOT_FOUND": 404,
    "ERR_NOTIFICATION_NOT_FOUND": 404,
    "ERR_SCREENING_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_PROPOSAL_NOT_FOUND": 404,
    "ERR_VOTE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # optimistic concurrency
    "ERR_STALE_YOUTH_VERSION": 412,
    "ERR_STALE_PLACEMENT_VERSION": 412,
    # state conflicts
    "ERR_ADMISSION_NOT_ACTIVE": 409,
    "ERR_ADMISSION_ALREADY_TERMINAL": 409,
    "ERR_YOUTH_ALREADY_SHELTERED": 409,
    "ERR_NOTIFICATION_ALREADY_RESOLVED": 409,
    "ERR_SCREENING_INVALID_TRANSITION": 409,
    "ERR_CASE_INVALID_STATE": 409,
    "ERR_SESSION_ALREADY_RECORDED": 409,
    "ERR_PLACEMENT_ALREADY_EXITED": 409,
    "ERR_PROPOSAL_ALREADY_DECIDED": 409,
    "ERR_PROPOSAL_VOTE_CLOSED": 409,
    "ERR_DUPLICATE_VOTE": 409,
    "ERR_ADMISSION_OVERLAP": 409,
    "ERR_MEDIATION_SESSION_OVERLAP": 409,
    "ERR_MEDIATION_COOLDOWN_ACTIVE": 409,
    "ERR_PLACEMENT_OVERLAP": 409,
    "ERR_BED_CAPACITY_EXCEEDED": 409,
    # business rules
    "ERR_SCREENING_CRITICAL_TIER": 422,
    "ERR_SCREENING_ESCALATED_BLOCKS_ACTION": 422,
    "ERR_YOUTH_POSTURE_FROZEN": 422,
    "ERR_RUNAWAY_REPORT_REQUIRED": 422,
    "ERR_NOTIFICATION_UNSAFE_CONTACT": 422,
    "ERR_NOTIFICATION_UNRESOLVED": 422,
    "ERR_AGE_OUTSIDE_PROGRAM_BAND": 422,
    "ERR_PROGRAM_TYPE_MISMATCH": 422,
    "ERR_SCREENING_REQUIRED": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_CLOCK_MONOTONIC_VIOLATION": 422,
    "ERR_MAX_STAY_EXCEEDED": 422,
    "ERR_MAX_EXTENSIONS_REACHED": 422,
    "ERR_MEDIATION_ROUNDS_EXHAUSTED": 422,
    "ERR_DURATION_LIMIT_REACHED": 422,
    "ERR_YOUTH_NOT_VOTE_ELIGIBLE": 422,
    "ERR_NO_ELIGIBLE_ELECTORATE": 422,
    "ERR_PROGRAM_RESTRICTED_PRIORITY": 422,
    "ERR_SAVINGS_INSUFFICIENT_BALANCE": 422,
    "ERR_SAVINGS_WITHDRAWAL_BLOCKED": 422,
    "ERR_SAVINGS_REVERSAL_UNMATCHED": 422,
    "ERR_YOUTH_POSTURE_RESTRICTED": 422,
    "ERR_AFTERCARE_WINDOW_MISSED": 422,
}

ERROR_MESSAGE = {
    "ERR_MISSING_AUTH_HEADERS": "Authentication headers are required",
    "ERR_UNAUTHORIZED_ROLE": "Role is not permitted to perform this operation",
    "ERR_NOT_VOTE_OWNER": "A vote may only be retracted by the youth who cast it",
    "ERR_SEGREGATION_OF_DUTIES": (
        "The reunification decision must be made by a different user than the one "
        "who recorded the mediation outcome"
    ),
    "ERR_PROGRAM_NOT_FOUND": "Shelter program not found",
    "ERR_YOUTH_NOT_FOUND": "Youth not found",
    "ERR_ADMISSION_NOT_FOUND": "Admission not found",
    "ERR_NOTIFICATION_NOT_FOUND": "Guardian notification not found",
    "ERR_SCREENING_NOT_FOUND": "Safety screening not found",
    "ERR_CASE_NOT_FOUND": "Reunification case not found",
    "ERR_SESSION_NOT_FOUND": "Mediation session not found",
    "ERR_PLACEMENT_NOT_FOUND": "Transitional living placement not found",
    "ERR_ENROLLMENT_NOT_FOUND": "Education enrollment not found",
    "ERR_PROPOSAL_NOT_FOUND": "Governance proposal not found",
    "ERR_VOTE_NOT_FOUND": "Governance vote not found",
    "ERR_INVALID_REQUEST": "Request body is invalid",
    "ERR_STALE_YOUTH_VERSION": "Youth has been modified by another writer",
    "ERR_STALE_PLACEMENT_VERSION": "Placement has been modified by another writer",
    "ERR_ADMISSION_NOT_ACTIVE": "Admission is not in an active stay",
    "ERR_ADMISSION_ALREADY_TERMINAL": "Admission has already reached a terminal state",
    "ERR_YOUTH_ALREADY_SHELTERED": "Youth already holds a non-terminal admission",
    "ERR_NOTIFICATION_ALREADY_RESOLVED": "Guardian notification has already been resolved",
    "ERR_SCREENING_INVALID_TRANSITION": "Screening disposition is not available from the current status",
    "ERR_CASE_INVALID_STATE": "Reunification case is not in a state that allows this step",
    "ERR_SESSION_ALREADY_RECORDED": "Mediation session outcome has already been recorded",
    "ERR_PLACEMENT_ALREADY_EXITED": "Placement tenancy has already ended",
    "ERR_PROPOSAL_ALREADY_DECIDED": "Governance proposal has already been decided",
    "ERR_PROPOSAL_VOTE_CLOSED": "Voting on this proposal is closed",
    "ERR_DUPLICATE_VOTE": "This youth has already cast a counted vote on this proposal",
    "ERR_ADMISSION_OVERLAP": "Requested stay overlaps an existing stay for this youth",
    "ERR_MEDIATION_SESSION_OVERLAP": "Mediation session overlaps another session for this case",
    "ERR_MEDIATION_COOLDOWN_ACTIVE": "A 72 hour cooldown applies after the previous mediation session",
    "ERR_PLACEMENT_OVERLAP": "Youth already holds an open transitional living placement",
    "ERR_BED_CAPACITY_EXCEEDED": "Program has no licensed bed available",
    "ERR_SCREENING_CRITICAL_TIER": (
        "Youth is in the critical trafficking risk tier and requires the specialized "
        "response pathway"
    ),
    "ERR_SCREENING_ESCALATED_BLOCKS_ACTION": "An escalated safety screening blocks this action",
    "ERR_YOUTH_POSTURE_FROZEN": "Youth posture is FROZEN and only safety operations are permitted",
    "ERR_RUNAWAY_REPORT_REQUIRED": "A law enforcement runaway report must be filed before this step",
    "ERR_NOTIFICATION_UNSAFE_CONTACT": "Guardian contact is unsafe for this youth",
    "ERR_NOTIFICATION_UNRESOLVED": "The parental notification obligation must be resolved first",
    "ERR_AGE_OUTSIDE_PROGRAM_BAND": "Youth age is outside the program's licensed age band",
    "ERR_PROGRAM_TYPE_MISMATCH": "Program type does not support this placement",
    "ERR_SCREENING_REQUIRED": "A safety screening is required before this action",
    "ERR_INVALID_INTERVAL": "Interval endpoints are not ordered correctly",
    "ERR_CLOCK_MONOTONIC_VIOLATION": "The logical clock may only move forward",
    "ERR_MAX_STAY_EXCEEDED": "Requested stay exceeds the program's federal maximum stay",
    "ERR_MAX_EXTENSIONS_REACHED": "This stay has already been extended the maximum number of times",
    "ERR_MEDIATION_ROUNDS_EXHAUSTED": "The case has used all permitted mediation rounds",
    "ERR_DURATION_LIMIT_REACHED": "Placement has reached its transitional living duration allowance",
    "ERR_YOUTH_NOT_VOTE_ELIGIBLE": "Youth is not eligible to participate in program governance",
    "ERR_NO_ELIGIBLE_ELECTORATE": "The program has no eligible youth electorate",
    "ERR_PROGRAM_RESTRICTED_PRIORITY": (
        "Program posture is RESTRICTED and only high priority admissions are accepted"
    ),
    "ERR_SAVINGS_INSUFFICIENT_BALANCE": "Savings balance is insufficient for this withdrawal",
    "ERR_SAVINGS_WITHDRAWAL_BLOCKED": "Withdrawals are blocked while the placement is on savings probation",
    "ERR_SAVINGS_REVERSAL_UNMATCHED": "Reversal exceeds the deposits recorded on this placement",
    "ERR_YOUTH_POSTURE_RESTRICTED": (
        "Youth posture is RESTRICTED and transitional living placement is not available"
    ),
    "ERR_AFTERCARE_WINDOW_MISSED": "The aftercare planning window has expired",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the app error handler."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
