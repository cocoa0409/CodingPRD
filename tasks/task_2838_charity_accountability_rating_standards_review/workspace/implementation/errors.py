"""Error catalog (PRD section 5) and the ApiError exception."""


ERROR_STATUS = {
    # 401
    "ERR_UNAUTHENTICATED": 401,
    # 403
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_NOT_ASSIGNED_ANALYST": 403,
    # 400
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # 404
    "ERR_ORGANIZATION_NOT_FOUND": 404,
    "ERR_METHODOLOGY_VERSION_NOT_FOUND": 404,
    "ERR_PUBLIC_COMMENT_NOT_FOUND": 404,
    "ERR_TRANSITION_GRANT_NOT_FOUND": 404,
    "ERR_RATING_CYCLE_NOT_FOUND": 404,
    "ERR_FILING_RECORD_NOT_FOUND": 404,
    "ERR_GOVERNANCE_PROFILE_NOT_FOUND": 404,
    "ERR_STANDARD_EVALUATION_NOT_FOUND": 404,
    "ERR_DIMENSION_SCORE_NOT_FOUND": 404,
    "ERR_CORRECTION_REQUEST_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_COMPLAINT_NOT_FOUND": 404,
    "ERR_PUBLICATION_RECORD_NOT_FOUND": 404,
    # 409
    "ERR_CYCLE_STATE_INVALID": 409,
    "ERR_FILING_STATE_INVALID": 409,
    "ERR_METHODOLOGY_STATE_INVALID": 409,
    "ERR_GOVERNANCE_STATE_INVALID": 409,
    "ERR_STANDARD_STATE_INVALID": 409,
    "ERR_CORRECTION_STATE_INVALID": 409,
    "ERR_APPEAL_STATE_INVALID": 409,
    "ERR_COMPLAINT_STATE_INVALID": 409,
    "ERR_CYCLE_NOT_PUBLISHABLE": 409,
    "ERR_METHODOLOGY_NOT_ADOPTED": 409,
    "ERR_CORRECTION_NOT_REJECTED": 409,
    "ERR_GOVERNANCE_NOT_EVALUATED": 409,
    "ERR_TRANSITION_GRACE_UNAVAILABLE": 409,
    "ERR_CLOCK_NOT_MONOTONIC": 409,
    "ERR_METHODOLOGY_NOT_EFFECTIVE": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 409,
    "ERR_METHODOLOGY_WINDOW_CONFLICT": 409,
    "ERR_CYCLE_PERIOD_OVERLAP": 409,
    "ERR_DUPLICATE_EIN": 409,
    "ERR_DUPLICATE_VERSION_LABEL": 409,
    "ERR_DUPLICATE_GOVERNANCE_PROFILE": 409,
    "ERR_COMMENT_PERIOD_CLOSED": 409,
    "ERR_UNRESOLVED_COMMENTS": 409,
    "ERR_CORRECTION_ROUND_LIMIT": 409,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_NO_VALIDATED_FILING": 409,
    "ERR_DATA_COMPLETENESS_TOO_LOW": 409,
    # 412
    "ERR_STALE_VERSION": 412,
    # 422
    "ERR_WEIGHTS_NOT_NORMALIZED": 422,
    "ERR_PANEL_COMPOSITION_INVALID": 422,
    "ERR_PENALTY_POINTS_RANGE": 422,
    "ERR_EXPENSE_COMPONENTS_MISMATCH": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or empty.",
    "ERR_ROLE_NOT_PERMITTED": "The supplied role is not permitted to perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the targeted resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this actor from this operation.",
    "ERR_NOT_ASSIGNED_ANALYST": "Only the assigned analyst of this rating cycle may perform this operation.",
    "ERR_INVALID_REQUEST": "The request body is malformed.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are invalid.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the stored version.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."
        )


NOT_FOUND_FOR_ENTITY = {
    "Organization": "ERR_ORGANIZATION_NOT_FOUND",
    "MethodologyVersion": "ERR_METHODOLOGY_VERSION_NOT_FOUND",
    "PublicComment": "ERR_PUBLIC_COMMENT_NOT_FOUND",
    "TransitionGrant": "ERR_TRANSITION_GRANT_NOT_FOUND",
    "RatingCycle": "ERR_RATING_CYCLE_NOT_FOUND",
    "FilingRecord": "ERR_FILING_RECORD_NOT_FOUND",
    "GovernanceProfile": "ERR_GOVERNANCE_PROFILE_NOT_FOUND",
    "StandardEvaluation": "ERR_STANDARD_EVALUATION_NOT_FOUND",
    "DimensionScore": "ERR_DIMENSION_SCORE_NOT_FOUND",
    "CorrectionRequest": "ERR_CORRECTION_REQUEST_NOT_FOUND",
    "Appeal": "ERR_APPEAL_NOT_FOUND",
    "Complaint": "ERR_COMPLAINT_NOT_FOUND",
    "PublicationRecord": "ERR_PUBLICATION_RECORD_NOT_FOUND",
}
