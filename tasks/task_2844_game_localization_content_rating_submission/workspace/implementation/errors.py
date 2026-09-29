"""Error catalogue (PRD SS5) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)


ERROR_STATUS = {
    # --- authentication / authorisation
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_OWNERSHIP_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- request shape
    "ERR_INVALID_REQUEST": 400,
    # --- existence
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_MARKET_PLAN_NOT_FOUND": 404,
    "ERR_STRING_KEY_NOT_FOUND": 404,
    "ERR_TRANSLATION_UNIT_NOT_FOUND": 404,
    "ERR_BOOTH_NOT_FOUND": 404,
    "ERR_TALENT_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_QA_PASS_NOT_FOUND": 404,
    "ERR_BUG_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_CONTENT_EDIT_NOT_FOUND": 404,
    # --- referential coherence
    "ERR_CROSS_PARENT_MISMATCH": 422,
    # --- optimistic concurrency
    "ERR_STALE_MARKET_PLAN_VERSION": 412,
    "ERR_STALE_TALENT_VERSION": 412,
    # --- uniqueness
    "ERR_DUPLICATE_TITLE_CODE": 409,
    "ERR_DUPLICATE_MARKET_CODE": 409,
    "ERR_DUPLICATE_STRING_KEY": 409,
    "ERR_OPEN_QA_PASS_EXISTS": 409,
    # --- own-state preconditions
    "ERR_TITLE_STRINGS_ALREADY_LOCKED": 409,
    "ERR_STRING_KEY_LOCKED": 409,
    "ERR_MARKET_PLAN_STATE_INVALID": 409,
    "ERR_UNIT_NOT_DELIVERED": 409,
    "ERR_CONTRACT_NOT_DRAFT": 409,
    "ERR_SESSION_STATE_INVALID": 409,
    "ERR_QA_PASS_NOT_OPEN": 409,
    "ERR_QA_PASS_NOT_CLOSED": 409,
    "ERR_BUG_STATE_INVALID": 409,
    "ERR_SUBMISSION_STATE_INVALID": 409,
    "ERR_CONTENT_EDIT_NOT_PROPOSED": 409,
    # --- cross-entity state
    "ERR_PREREQUISITE_STATE_NOT_MET": 409,
    # --- domain business rules
    "ERR_MANDATORY_DISCLOSURE_MISSING": 422,
    "ERR_CONTENT_RESTRICTION_UNRESOLVED": 422,
    "ERR_FOOTAGE_EVIDENCE_MISSING": 422,
    "ERR_CONTRACT_TERRITORY_NOT_COVERED": 422,
    "ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED": 422,
    "ERR_SESSION_SPANS_TWO_DATES": 422,
    "ERR_DEFECT_DENSITY_EXCEEDED": 422,
    "ERR_TEXT_OVERFLOW_UNRESOLVED": 422,
    "ERR_LOCALIZATION_INCOMPLETE": 422,
    "ERR_RATING_BAND_MISMATCH": 422,
    "ERR_MAX_APPEALS_EXCEEDED": 422,
    "ERR_BOOTH_WINDOW_CONFLICT": 409,
    "ERR_TALENT_DAILY_CAPACITY_EXCEEDED": 409,
    "ERR_BUDGET_OVERAGE": 422,
    # --- generic fallbacks
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

ERROR_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognised authentication headers",
    "ERR_ROLE_NOT_PERMITTED": "Role is not permitted to call this endpoint",
    "ERR_OWNERSHIP_VIOLATION": "Acting talent does not own the target resource",
    "ERR_SEGREGATION_OF_DUTIES": "The same user may not perform both halves of this control",
    "ERR_INVALID_REQUEST": "Request payload failed structural validation",
    "ERR_TITLE_NOT_FOUND": "Title not found",
    "ERR_MARKET_PLAN_NOT_FOUND": "Market plan not found",
    "ERR_STRING_KEY_NOT_FOUND": "String key not found",
    "ERR_TRANSLATION_UNIT_NOT_FOUND": "Translation unit not found",
    "ERR_BOOTH_NOT_FOUND": "Recording booth not found",
    "ERR_TALENT_NOT_FOUND": "Voice talent not found",
    "ERR_CONTRACT_NOT_FOUND": "Talent contract not found",
    "ERR_SESSION_NOT_FOUND": "Voice session not found",
    "ERR_QA_PASS_NOT_FOUND": "QA pass not found",
    "ERR_BUG_NOT_FOUND": "LQA bug not found",
    "ERR_SUBMISSION_NOT_FOUND": "Rating submission not found",
    "ERR_CONTENT_EDIT_NOT_FOUND": "Content edit not found",
    "ERR_CROSS_PARENT_MISMATCH": "Referenced rows do not share the required parent",
    "ERR_STALE_MARKET_PLAN_VERSION": "expected_market_plan_version does not match the stored version",
    "ERR_STALE_TALENT_VERSION": "expected_voice_talent_version does not match the stored version",
    "ERR_DUPLICATE_TITLE_CODE": "title_code already exists",
    "ERR_DUPLICATE_MARKET_CODE": "market_code already exists for this title",
    "ERR_DUPLICATE_STRING_KEY": "key_name already exists for this title",
    "ERR_OPEN_QA_PASS_EXISTS": "An OPEN QA pass of that pass_type already exists",
    "ERR_TITLE_STRINGS_ALREADY_LOCKED": "Title is no longer in PLANNING",
    "ERR_STRING_KEY_LOCKED": "String key is no longer EXTRACTED",
    "ERR_MARKET_PLAN_STATE_INVALID": "Market plan status does not permit this transition",
    "ERR_UNIT_NOT_DELIVERED": "Translation unit is not in a status that permits this operation",
    "ERR_CONTRACT_NOT_DRAFT": "Contract status does not permit this transition",
    "ERR_SESSION_STATE_INVALID": "Session status does not permit this transition",
    "ERR_QA_PASS_NOT_OPEN": "QA pass is not OPEN",
    "ERR_QA_PASS_NOT_CLOSED": "QA pass is not CLOSED",
    "ERR_BUG_STATE_INVALID": "Defect status does not permit this transition",
    "ERR_SUBMISSION_STATE_INVALID": "Submission status does not permit this transition",
    "ERR_CONTENT_EDIT_NOT_PROPOSED": "Content edit is not PROPOSED",
    "ERR_PREREQUISITE_STATE_NOT_MET": "A related entity is not in the required state",
    "ERR_MANDATORY_DISCLOSURE_MISSING": "A mandatory content descriptor was not disclosed",
    "ERR_CONTENT_RESTRICTION_UNRESOLVED": "A restricted content descriptor is still disclosed",
    "ERR_FOOTAGE_EVIDENCE_MISSING": "Footage evidence is required for the disclosed descriptors",
    "ERR_CONTRACT_TERRITORY_NOT_COVERED": "Contract rights do not cover this market",
    "ERR_CONTRACT_RIGHTS_WINDOW_EXCEEDED": "Requested window falls outside the contract rights window",
    "ERR_SESSION_SPANS_TWO_DATES": "A session must start and end on the same UTC date",
    "ERR_DEFECT_DENSITY_EXCEEDED": "Defect density is at or above the ceiling",
    "ERR_TEXT_OVERFLOW_UNRESOLVED": "Text overflow remains unresolved",
    "ERR_LOCALIZATION_INCOMPLETE": "Localization deliverables are incomplete",
    "ERR_RATING_BAND_MISMATCH": "Assigned rating band is incompatible with the target rating",
    "ERR_MAX_APPEALS_EXCEEDED": "The appeal allowance for this submission is exhausted",
    "ERR_BOOTH_WINDOW_CONFLICT": "Booth is already occupied for the requested window",
    "ERR_TALENT_DAILY_CAPACITY_EXCEEDED": "Talent daily recording capacity would be exceeded",
    "ERR_BUDGET_OVERAGE": "Market plan is over budget",
    "ERR_NOT_FOUND": "Resource not found",
    "ERR_METHOD_NOT_ALLOWED": "Method not allowed",
    "ERR_INTERNAL": "Internal server error",
}
