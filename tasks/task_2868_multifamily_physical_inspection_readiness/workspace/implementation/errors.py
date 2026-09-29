"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication and authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_FORBIDDEN_NOT_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 422,
    # existence
    "ERR_STANDARD_NOT_FOUND": 404,
    "ERR_DEFECT_DEFINITION_NOT_FOUND": 404,
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_INSPECTION_NOT_FOUND": 404,
    "ERR_SAMPLE_SELECTION_NOT_FOUND": 404,
    "ERR_DEFICIENCY_NOT_FOUND": 404,
    "ERR_SWEEP_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_CAP_NOT_FOUND": 404,
    "ERR_CAPITAL_NEED_NOT_FOUND": 404,
    # state admissibility
    "ERR_STANDARD_ALREADY_ADOPTED": 409,
    "ERR_INSPECTION_INVALID_STATE": 409,
    "ERR_SELECTION_INVALID_STATE": 409,
    "ERR_DEFICIENCY_INVALID_STATE": 409,
    "ERR_SWEEP_INVALID_STATE": 409,
    "ERR_WORK_ORDER_INVALID_STATE": 409,
    "ERR_APPEAL_INVALID_STATE": 409,
    "ERR_CAP_INVALID_STATE": 409,
    "ERR_APPEAL_PENDING": 409,
    "ERR_FOLLOW_UP_NOT_CLOSED": 409,
    # optimistic concurrency
    "ERR_STALE_INSPECTION_VERSION": 412,
    "ERR_STALE_SWEEP_VERSION": 412,
    "ERR_STALE_PROPERTY_VERSION": 412,
    # life safety gating
    "ERR_PROPERTY_FROZEN": 409,
    "ERR_LIFE_THREATENING_UNCORRECTED": 409,
    "ERR_LT_CORRECTION_DEADLINE_PASSED": 422,
    # referential business rules
    "ERR_STANDARD_NOT_ADOPTED": 409,
    "ERR_DEFECT_DEFINITION_STANDARD_MISMATCH": 422,
    "ERR_AREA_MISMATCH": 422,
    "ERR_AREA_OUT_OF_SCOPE": 422,
    "ERR_DEFICIENCY_NOT_IN_INSPECTION": 422,
    # temporal rules
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_INSPECTION_WINDOW_CONFLICT": 409,
    "ERR_UNIT_ACCESS_WINDOW_CONFLICT": 409,
    "ERR_SWEEP_CAPACITY_EXCEEDED": 409,
    "ERR_FOLLOW_UP_TOO_EARLY": 422,
    # remaining business constraints
    "ERR_NOTICE_WINDOW_TOO_SHORT": 422,
    "ERR_NO_ELIGIBLE_UNITS": 422,
    "ERR_UNIT_NOT_IN_SAMPLE": 422,
    "ERR_UNIT_ACCESS_NOT_GRANTED": 409,
    "ERR_ACCESS_NOT_RECORDED": 409,
    "ERR_WEIGHTS_NOT_NORMALIZED": 422,
    "ERR_LT_DEADLINE_MUST_BE_24H": 422,
    "ERR_NO_LIFE_THREATENING_DEFINITION": 422,
    "ERR_DUPLICATE_STANDARD_CODE": 409,
    "ERR_DUPLICATE_DEFECT_CODE": 409,
    "ERR_DUPLICATE_UNIT_NUMBER": 409,
    "ERR_APPEAL_RESUBMIT_LIMIT": 409,
    "ERR_SWEEP_CLOSURE_RATE_TOO_LOW": 409,
    # fiscal constraints
    "ERR_CAP_COST_EXCEEDS_RESERVE": 422,
    "ERR_CAP_TARGET_AFTER_DEADLINE": 422,
    "ERR_ADJUSTMENT_REQUIRED": 422,
    "ERR_ADJUSTMENT_EXCEEDS_POINTS": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or the declared role is not recognised.",
    "ERR_UNAUTHORIZED": "The declared role is not authorised for this endpoint.",
    "ERR_FORBIDDEN_NOT_OWNER": "The acting property owner does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The verifying operator may not be the completing operator.",
    "ERR_INVALID_REQUEST": "The request body failed shape validation.",
    "ERR_INVALID_ENUM_VALUE": "An enum-typed field carries a value outside its enumeration.",
}


class ApiError(Exception):
    """A rejected request carrying one catalogue error id."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, "The request was rejected by rule %s." % error_id
        )
