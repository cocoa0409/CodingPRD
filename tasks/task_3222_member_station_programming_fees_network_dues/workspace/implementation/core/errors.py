"""The error catalogue (ids and HTTP statuses) and the ApiError carrier."""

ERR_STATUS = {
    "ERR_MISSING_AUTH": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CALL_SIGN_TAKEN": 409,
    "ERR_PROGRAM_CODE_TAKEN": 409,
    "ERR_FEED_CODE_TAKEN": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STATION_NOT_ELIGIBLE": 409,
    "ERR_STATION_SUSPENDED": 409,
    "ERR_VOTE_ALREADY_RECORDED": 409,
    "ERR_REVIEW_INCOMPLETE": 409,
    "ERR_CARRIAGE_AGREEMENT_TERMINATED": 409,
    "ERR_SEGMENT_COUNT_EXCEEDED": 409,
    "ERR_CANDIDACY_NOT_QUALIFIED": 409,
    "ERR_WINDOW_OVERLAP": 409,
    "ERR_EMBARGO_VIOLATION": 409,
    "ERR_PROGRAM_CODE_MISMATCH": 409,
    "ERR_SLOT_STATION_MISMATCH": 409,
    "ERR_UPLINK_CAPACITY_CONFLICT": 409,
    "ERR_UPLINK_CAPACITY_EXHAUSTED": 409,
    "ERR_CONTRIBUTION_STATION_INELIGIBLE": 409,
    "ERR_ACK_LANGUAGE_VIOLATION": 422,
    "ERR_TRANSMISSION_FREEZE": 422,
    "ERR_DUES_VOTE_IN_PROGRESS": 422,
    "ERR_DUES_PROPOSAL_REJECTED": 422,
    "ERR_POOL_OVER_ALLOCATED": 422,
    "ERR_ARCHIVE_INVARIANT_VIOLATED": 422,
    "ERR_SLOT_REQUEST_LIMIT_EXCEEDED": 422,
    "ERR_NO_ELIGIBLE_STATION_CAUSE": 422,
    "ERR_STALE_STATION_VERSION": 412,
    "ERR_STALE_PROGRAM_VERSION": 412,
    "ERR_STALE_ELECTION_VERSION": 412,
    "ERR_STALE_PROPOSAL_VERSION": 412,
}

# The acknowledgement language rules are evaluated in this order and the FIRST
# violation found is the one that is reported.
FORBIDDEN_PHRASES = [
    "best", "cheapest", "lowest price", "guarantee", "free", "sale",
    "bestseller", "recommend",
]
COMPARATIVE_TOKENS = ["better than", "outperforms", "cheaper than"]
CALL_TO_ACTION_TOKENS = ["call now", "visit today", "buy"]
MAX_ACK_WORDS = 30
VIOLATION_ORDER = [
    "SUPERLATIVE", "COMPARATIVE", "PRICE_INVITATION", "CALL_TO_ACTION", "LENGTH",
]

VIOLATION_MESSAGES = {
    "SUPERLATIVE": "acknowledgment script uses superlative language",
    "COMPARATIVE": "acknowledgment script makes a comparative claim",
    "PRICE_INVITATION": "acknowledgment script contains a price invitation",
    "CALL_TO_ACTION": "acknowledgment script contains a call to action",
    "LENGTH": "acknowledgment script exceeds the 30 word limit",
}

MESSAGES = {
    "ERR_MISSING_AUTH": "credentials are missing or the acting role is not recognised",
    "ERR_FORBIDDEN_ROLE": "the acting role may not perform this operation",
    "ERR_RESOURCE_NOT_FOUND": "the named resource does not exist",
    "ERR_INVALID_REQUEST": "the request is malformed",
    "ERR_CALL_SIGN_TAKEN": "the call sign is already registered",
    "ERR_PROGRAM_CODE_TAKEN": "the program code is already in use",
    "ERR_FEED_CODE_TAKEN": "the feed code is already in use",
    "ERR_INVALID_STATE": "the resource is not in a state that admits this transition",
    "ERR_ALREADY_TERMINAL": "the resource is in a terminal state",
    "ERR_STATION_NOT_ELIGIBLE": "the station is not eligible or on probation",
    "ERR_STATION_SUSPENDED": "the station is suspended or withdrawn",
    "ERR_VOTE_ALREADY_RECORDED": "the station already holds a recorded vote on this proposal",
    "ERR_REVIEW_INCOMPLETE": "an in-scope resource has not been cleared or has not qualified",
    "ERR_CARRIAGE_AGREEMENT_TERMINATED": "the parent carriage agreement is terminated",
    "ERR_SEGMENT_COUNT_EXCEEDED": "the required segment count has already aired",
    "ERR_CANDIDACY_NOT_QUALIFIED": "a candidacy is not qualified for certification",
    "ERR_WINDOW_OVERLAP": "the requested window overlaps a sibling window",
    "ERR_EMBARGO_VIOLATION": "the requested window breaches an embargo",
    "ERR_PROGRAM_CODE_MISMATCH": "the window program code differs from its agreement",
    "ERR_SLOT_STATION_MISMATCH": "the slot station differs from its window's station",
    "ERR_UPLINK_CAPACITY_CONFLICT": "the requested uplink interval overlaps a sibling slot",
    "ERR_UPLINK_CAPACITY_EXHAUSTED": "the feed has insufficient unreserved capacity",
    "ERR_CONTRIBUTION_STATION_INELIGIBLE": "the contributing station is not eligible or on probation",
    "ERR_ACK_LANGUAGE_VIOLATION": "the acknowledgment script violates a language rule",
    "ERR_TRANSMISSION_FREEZE": "the station is under an underwriting freeze",
    "ERR_DUES_VOTE_IN_PROGRESS": "an unsettled vote pair blocks a new vote",
    "ERR_DUES_PROPOSAL_REJECTED": "the proposal was rejected by its tally",
    "ERR_POOL_OVER_ALLOCATED": "the pool cannot be distributed without exceeding it",
    "ERR_ARCHIVE_INVARIANT_VIOLATED": "the credit ledger is not conserved at archive time",
    "ERR_SLOT_REQUEST_LIMIT_EXCEEDED": "a block request may carry at most three reservations",
    "ERR_NO_ELIGIBLE_STATION_CAUSE": "the candidate set is empty",
    "ERR_STALE_STATION_VERSION": "the supplied station version is stale",
    "ERR_STALE_PROGRAM_VERSION": "the supplied program version is stale",
    "ERR_STALE_ELECTION_VERSION": "the supplied election version is stale",
    "ERR_STALE_PROPOSAL_VERSION": "the supplied proposal version is stale",
}


class ApiError(Exception):
    """Carries the error id and the HTTP status it answers with."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERR_STATUS.get(error_id, 400)
        super().__init__("%s: %s" % (self.error_id, self.message))


def bad_request(message="the request is malformed"):
    return ApiError("ERR_INVALID_REQUEST", message)


def not_found(what="resource"):
    return ApiError("ERR_RESOURCE_NOT_FOUND", "no such %s" % what)


def invalid_state(message="the resource is not in a state that admits this transition"):
    return ApiError("ERR_INVALID_STATE", message)


def ack_violation(violation):
    return ApiError(
        "ERR_ACK_LANGUAGE_VIOLATION",
        VIOLATION_MESSAGES.get(violation, MESSAGES["ERR_ACK_LANGUAGE_VIOLATION"]),
    )