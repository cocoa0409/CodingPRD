"""Error catalog (PRD section 5) and the ApiError exception carried through the stack."""


# error_id -> HTTP status, verbatim from PRD section 5 / SCAFFOLD section 1.6.
ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_LEAGUE_NOT_FOUND": 404,
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_PLAYER_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_TEAM_HOUSE_NOT_FOUND": 404,
    "ERR_PRACTICE_BLOCK_NOT_FOUND": 404,
    "ERR_DEAL_NOT_FOUND": 404,
    "ERR_DELIVERABLE_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_ROSTER_MOVE_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_DEAL_VERSION_STALE": 412,
    "ERR_ORGANIZATION_VERSION_STALE": 412,
    # state preconditions
    "ERR_OFFER_EXPIRED": 409,
    "ERR_OFFER_NOT_OPEN": 409,
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": 409,
    "ERR_PLAYER_ALREADY_SIGNED": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_BLOCK_NOT_SCHEDULED": 409,
    "ERR_DEAL_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_NOT_SUBMITTED": 409,
    "ERR_DISTRIBUTION_NOT_DRAFT": 409,
    "ERR_DISTRIBUTION_NOT_CALCULATED": 409,
    "ERR_MOVE_NOT_PENDING": 409,
    "ERR_MOVE_NOT_APPROVED": 409,
    "ERR_MOVE_NOT_EXECUTED": 409,
    "ERR_MOVE_NOT_REVERSIBLE": 422,
    # minor protection, education and wellness
    "ERR_GUARDIAN_CONSENT_REQUIRED": 422,
    "ERR_MINOR_CATEGORY_FORBIDDEN": 422,
    "ERR_EDUCATION_HOURS_RESERVED": 422,
    "ERR_WEEKLY_HOUR_CAP_EXCEEDED": 422,
    "ERR_WELLNESS_HOLD_ACTIVE": 409,
    "ERR_OBLIGATION_BREACH_BLOCKS_ASSIGNMENT": 422,
    # league calendar
    "ERR_ROSTER_LOCK_ACTIVE": 422,
    "ERR_TRANSFER_WINDOW_CLOSED": 422,
    "ERR_FREE_AGENCY_COOLDOWN": 422,
    "ERR_EFFECTIVE_AT_OUTSIDE_SEASON": 422,
    "ERR_DELIVERABLE_DUE_OUTSIDE_DEAL": 422,
    "ERR_BLOCK_NOT_FINISHED": 409,
    # facility, quota and roster constraints
    "ERR_FACILITY_SLOT_CONFLICT": 409,
    "ERR_PLAYER_DOUBLE_BOOKED": 409,
    "ERR_FACILITY_CAPACITY_EXCEEDED": 422,
    "ERR_DELIVERABLE_QUOTA_EXCEEDED": 422,
    "ERR_TRYOUT_REQUIRED": 422,
    "ERR_ROSTER_SIZE_EXCEEDED": 422,
    "ERR_ROSTER_SIZE_BELOW_MINIMUM": 422,
    "ERR_EXCLUSIVITY_CONFLICT": 409,
    # fiscal / association terms
    "ERR_BELOW_MINIMUM_SALARY": 422,
    "ERR_PRIZE_SPLIT_BELOW_ASSOCIATION_MIN": 422,
    "ERR_STREAMING_HOURS_EXCEED_ASSOCIATION_MAX": 422,
    "ERR_SALARY_CAP_EXCEEDED": 422,
    "ERR_NEGATIVE_SETTLEMENT": 422,
    "ERR_NO_ELIGIBLE_CONTRACTS": 422,
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline; rendered by the Flask error handler."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)
        super().__init__(self.message)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request refused: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)
