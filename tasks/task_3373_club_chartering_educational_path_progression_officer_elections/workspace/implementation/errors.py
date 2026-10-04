"""Error catalog for the Club Chartering Path Progression API.

Every error_id and HTTP status below is taken verbatim from the scaffold error
catalog (SCAFFOLD.yaml section 1.6) and PRD section 5.
"""


class ApiError(Exception):
    """Carries the error_id, human message and HTTP status of a failed check."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
        self.http_status = http_status or STATUS_BY_ERROR.get(error_id, 400)
        super().__init__(self.message)


# error_id -> HTTP status (PRD section 5 catalogue)
STATUS_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_PATH_ENROLLMENT": 409,
    "ERR_DUPLICATE_ASSIGNMENT": 409,
    "ERR_DUPLICATE_BALLOT": 409,
    "ERR_OFFICE_ALREADY_FILLED": 409,
    "ERR_MEETING_OVERLAP": 409,
    "ERR_ROLE_WINDOW_EXCEEDED": 409,
    "ERR_ROLE_SLOTS_FULL": 409,
    "ERR_CONTEST_NOT_OPEN": 409,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_DUES_ALREADY_PAID": 409,
    "ERR_ORGANIZING_MEETING_REQUIRED": 422,
    "ERR_CHARTER_MINIMUM_NOT_MET": 422,
    "ERR_CORPORATE_SPONSOR_REQUIRED": 422,
    "ERR_SPONSOR_NOT_IN_GOOD_STANDING": 422,
    "ERR_LEVEL_REQUIREMENTS_NOT_MET": 422,
    "ERR_EVALUATOR_CONFLICT": 422,
    "ERR_JUDGE_CONFLICT": 422,
    "ERR_ELECTION_QUORUM_NOT_MET": 422,
    "ERR_CLUB_NOT_CHARTERED": 422,
    "ERR_CLUB_REVOKED": 422,
    "ERR_CLUB_NOT_IN_GOOD_STANDING": 422,
    "ERR_MEMBERSHIP_NOT_ACTIVE": 422,
    "ERR_NO_JUDGED_ENTRIES": 422,
    "ERR_NO_COACHING_CANDIDATES": 404,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be one of WorldHeadquarters, ClubOfficer, Member, DistrictDirector.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted on this endpoint, or the ownership clause for the acting role does not hold.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
    "ERR_INVALID_REQUEST": "The request payload is not structurally valid.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the current version of the parent resource.",
    "ERR_INVALID_STATE": "The target resource is not in a status that admits the requested transition.",
    "ERR_DUPLICATE_PATH_ENROLLMENT": "The membership already holds an education path for this path_code in status ACTIVE or SUSPENDED.",
    "ERR_DUPLICATE_ASSIGNMENT": "The member already holds an ASSIGNED role assignment on this meeting.",
    "ERR_DUPLICATE_BALLOT": "The judge already recorded a ballot for this contest entry.",
    "ERR_OFFICE_ALREADY_FILLED": "The club, term index and office already carry an ELECTED or TRAINED term, or the member already holds one.",
    "ERR_MEETING_OVERLAP": "The candidate meeting intersects, or starts inside the 30-minute buffer of, another SCHEDULED or HELD meeting at the same club.",
    "ERR_ROLE_WINDOW_EXCEEDED": "The member already holds 2 SPEECH role assignments inside the rolling 7-day window around the meeting.",
    "ERR_ROLE_SLOTS_FULL": "The meeting already holds 7 role assignments in status ASSIGNED, COMPLETED or NO_SHOW.",
    "ERR_CONTEST_NOT_OPEN": "The contest is not open for this operation.",
    "ERR_QUORUM_NOT_MET": "A meeting cannot be closed as HELD with an attendance count below 5.",
    "ERR_DUES_ALREADY_PAID": "The invoice is already PAID or has been VOIDed.",
    "ERR_ORGANIZING_MEETING_REQUIRED": "The organizing meeting must be held with at least 3 attendees before a charter can be granted.",
    "ERR_CHARTER_MINIMUM_NOT_MET": "A charter requires at least 20 dues-paid memberships.",
    "ERR_CORPORATE_SPONSOR_REQUIRED": "A CORPORATE club requires a corporate_sponsor_name.",
    "ERR_SPONSOR_NOT_IN_GOOD_STANDING": "The named sponsor club is not CHARTERED with good_standing GOOD.",
    "ERR_LEVEL_REQUIREMENTS_NOT_MET": "The path does not hold enough approved speeches or projects for its current level.",
    "ERR_EVALUATOR_CONFLICT": "The evaluator must differ from the member who owns the completion.",
    "ERR_JUDGE_CONFLICT": "The judge must differ from the competing member and must not hold a membership at the entry's club.",
    "ERR_ELECTION_QUORUM_NOT_MET": "The election requires a HELD meeting carrying quorum after the nomination and a nominee whose membership is ACTIVE and paid through the current cycle.",
    "ERR_CLUB_NOT_CHARTERED": "Dues renewal is refused while the club charter_status is SUSPENDED.",
    "ERR_CLUB_REVOKED": "The club charter_status is REVOKED.",
    "ERR_CLUB_NOT_IN_GOOD_STANDING": "The club good_standing is not GOOD.",
    "ERR_MEMBERSHIP_NOT_ACTIVE": "The membership is not ACTIVE or its dues_paid_through_cycle is below the club's dues_cycle_index.",
    "ERR_NO_JUDGED_ENTRIES": "The contest has no entry in status JUDGED.",
    "ERR_NO_COACHING_CANDIDATES": "No club is in PROBATION or NOT_IN_GOOD_STANDING with coaching_status NONE.",
}


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)


def not_found(message=None):
    return ApiError("ERR_NOT_FOUND", message)


def invalid_state(message=None):
    return ApiError("ERR_INVALID_STATE", message)
