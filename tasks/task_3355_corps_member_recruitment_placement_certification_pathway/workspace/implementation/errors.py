"""Error catalogue for the corps recruitment / placement / certification API."""

# error_id -> (http_status, default message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "Missing or unrecognized authentication headers."),
    "ERR_FORBIDDEN_ROLE": (403, "The acting role is not authorized for this operation."),
    "ERR_INVALID_REQUEST": (400, "The request body is missing a required field or carries an invalid value."),
    "ERR_REGION_NOT_FOUND": (404, "The referenced region does not exist."),
    "ERR_DISTRICT_NOT_FOUND": (404, "The referenced partner district does not exist."),
    "ERR_SCHOOL_NOT_FOUND": (404, "The referenced partner school does not exist."),
    "ERR_APPLICANT_NOT_FOUND": (404, "The referenced applicant does not exist."),
    "ERR_APPLICATION_NOT_FOUND": (404, "The referenced application does not exist."),
    "ERR_PATHWAY_NOT_FOUND": (404, "The referenced certification pathway does not exist."),
    "ERR_MEMBER_NOT_FOUND": (404, "The referenced corps member does not exist."),
    "ERR_PLACEMENT_NOT_FOUND": (404, "The referenced placement does not exist."),
    "ERR_MILESTONE_NOT_FOUND": (404, "The referenced certification milestone does not exist."),
    "ERR_INVALID_STATE": (409, "The resource is not in a state that permits this transition."),
    "ERR_ALREADY_TERMINAL": (409, "The resource already sits in a terminal state."),
    "ERR_OFFER_EXPIRED": (409, "The offer window has closed."),
    "ERR_DISTRICT_NOT_ACTIVE": (409, "The partner district agreement is not ACTIVE."),
    "ERR_MEMBER_NOT_ACTIVE": (409, "The corps member is not in ACTIVE service."),
    "ERR_INSTITUTE_INCOMPLETE": (409, "The corps member has not completed the pre-service institute."),
    "ERR_SOD_VIOLATION": (403, "Segregation of duties violation."),
    "ERR_DUPLICATE_APPLICATION": (409, "The applicant already holds a live application."),
    "ERR_SCHOOL_CAPACITY_EXCEEDED": (409, "The school cannot host another overlapping placement."),
    "ERR_COACH_SCHEDULE_OVERLAP": (409, "The coach already has an overlapping coaching session."),
    "ERR_MILESTONE_PAST_DUE": (422, "The certification milestone is past its state deadline."),
    "ERR_PATHWAY_REGION_MISMATCH": (422, "The certification pathway belongs to a different region."),
    "ERR_DISTRICT_BUDGET_EXCEEDED": (402, "The placement would push the district past its fee budget."),
    "ERR_SCORE_BELOW_THRESHOLD": (422, "The final selection score is below the SELECT band."),
    "ERR_PRACTICE_HOURS_EXCEEDED": (422, "The practice-hour delta exceeds the 480-hour ceiling."),
    "ERR_STALE_MEMBER_VERSION": (412, "The observed corps member version is stale."),
    "ERR_STALE_DISTRICT_VERSION": (412, "The observed partner district version is stale."),
}


class ApiError(Exception):
    """Carries the exact error_id / http status declared in the error catalogue."""

    def __init__(self, error_id, message=None, http_status=None):
        if error_id not in ERRORS:
            raise ValueError("unknown error id: %s" % error_id)
        declared_status, declared_message = ERRORS[error_id]
        self.error_id = error_id
        self.message = message or declared_message
        self.http_status = http_status or declared_status
        super().__init__("%s: %s" % (self.error_id, self.message))
