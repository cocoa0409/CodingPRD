"""Error catalogue (PRD section 5) and the exception that carries it."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_STATUS = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # existence
    "ERR_SELLER_NOT_FOUND": 404,
    "ERR_POLICY_RULE_NOT_FOUND": 404,
    "ERR_LISTING_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_EVALUATION_NOT_FOUND": 404,
    "ERR_ACTION_NOT_FOUND": 404,
    "ERR_POA_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_HOLD_NOT_FOUND": 404,
    "ERR_LINK_NOT_FOUND": 404,
    # shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_POA_INCOMPLETE": 422,
    # state
    "ERR_SELLER_BANNED": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_VIOLATION_NOT_SUBSTANTIATED": 409,
    "ERR_SELLER_NOT_UNDER_HOLD_POSTURE": 409,
    "ERR_ACTION_NOT_APPEALABLE_STATE": 409,
    "ERR_POA_NOT_ACCEPTED": 409,
    "ERR_LISTING_NOT_REMOVED": 409,
    "ERR_HOLD_NOT_MANUALLY_RELEASABLE": 409,
    "ERR_SELLER_NOT_BANNED": 409,
    # occ
    "ERR_STALE_SELLER_VERSION": 412,
    "ERR_STALE_ACTION_VERSION": 412,
    # safety
    "ERR_REPEAT_OFFENSE_DENIAL": 422,
    "ERR_LINK_MATCH_NOT_BANNED": 422,
    "ERR_LISTING_RESTRICTED_NO_RELIST": 422,
    "ERR_OVERRIDE_NOT_MORE_SEVERE": 422,
    # temporal / geometry
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_ESCALATION_WINDOW_CLOSED": 422,
    "ERR_SNAPSHOT_WINDOW_OVERLAP": 422,
    "ERR_HOLD_COVERAGE_OVERLAP": 422,
    "ERR_NO_SNAPSHOTS_IN_WINDOW": 422,
    # uniqueness
    "ERR_DUPLICATE_SELLER_EMAIL": 409,
    "ERR_DUPLICATE_POLICY_CODE": 409,
    "ERR_ACTION_ALREADY_EXISTS": 409,
    "ERR_APPEAL_ALREADY_EXISTS": 409,
    "ERR_POA_ALREADY_OPEN": 409,
    "ERR_POA_REVISION_LIMIT": 409,
    # coherence
    "ERR_LISTING_SELLER_MISMATCH": 422,
    "ERR_LISTING_REQUIRED_FOR_SCOPE": 422,
    "ERR_REPORTER_NOT_ELIGIBLE": 422,
    "ERR_POA_ACTION_MISMATCH": 422,
    "ERR_HOLD_ACTION_SELLER_MISMATCH": 422,
    # money
    "ERR_HOLD_EXCEEDS_AVAILABLE": 422,
    "ERR_FORFEIT_EXCEEDS_HOLD": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing or invalid.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting seller does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The acting user already performed a conflicting earlier step.",
    "ERR_SELLER_NOT_FOUND": "No seller with the given id.",
    "ERR_POLICY_RULE_NOT_FOUND": "No policy rule with the given id.",
    "ERR_LISTING_NOT_FOUND": "No listing with the given id.",
    "ERR_VIOLATION_NOT_FOUND": "No violation with the given id.",
    "ERR_EVALUATION_NOT_FOUND": "No health evaluation with the given id.",
    "ERR_ACTION_NOT_FOUND": "No enforcement action with the given id.",
    "ERR_POA_NOT_FOUND": "No plan of action with the given id.",
    "ERR_APPEAL_NOT_FOUND": "No appeal with the given id.",
    "ERR_HOLD_NOT_FOUND": "No disbursement hold with the given id.",
    "ERR_LINK_NOT_FOUND": "No related-account link with the given id.",
    "ERR_INVALID_REQUEST": "The request payload or query is malformed.",
    "ERR_POA_INCOMPLETE": "The plan of action does not satisfy the content requirements.",
    "ERR_SELLER_BANNED": "The seller reached from the target row is banned.",
    "ERR_INVALID_STATE": "The target row is not in a state that admits this transition.",
    "ERR_VIOLATION_NOT_SUBSTANTIATED": "The cited violation is not substantiated.",
    "ERR_SELLER_NOT_UNDER_HOLD_POSTURE": "The seller's disbursement state is NORMAL.",
    "ERR_ACTION_NOT_APPEALABLE_STATE": "The enforcement action is already upheld or vacated.",
    "ERR_POA_NOT_ACCEPTED": "No accepted plan of action backs this appeal.",
    "ERR_LISTING_NOT_REMOVED": "The listing is not in state REMOVED.",
    "ERR_HOLD_NOT_MANUALLY_RELEASABLE": "A sweeping full hold cannot be released manually.",
    "ERR_SELLER_NOT_BANNED": "The hold's seller is not banned.",
    "ERR_STALE_SELLER_VERSION": "expected_seller_version does not match the seller's version.",
    "ERR_STALE_ACTION_VERSION": "expected_enforcement_action_version does not match the action's version.",
    "ERR_REPEAT_OFFENSE_DENIAL": "Reinstatement is unavailable for a repeat offender.",
    "ERR_LINK_MATCH_NOT_BANNED": "The matched seller was not banned at detection.",
    "ERR_LISTING_RESTRICTED_NO_RELIST": "A restricted-product removal may never be relisted.",
    "ERR_OVERRIDE_NOT_MORE_SEVERE": "The override is not strictly more severe than the computed rung.",
    "ERR_APPEAL_WINDOW_CLOSED": "The appeal window has closed.",
    "ERR_ESCALATION_WINDOW_CLOSED": "The escalation window has closed.",
    "ERR_SNAPSHOT_WINDOW_OVERLAP": "The measurement window overlaps an existing window.",
    "ERR_HOLD_COVERAGE_OVERLAP": "The coverage interval is too close to an existing active hold.",
    "ERR_NO_SNAPSHOTS_IN_WINDOW": "No metric snapshot falls inside the lookback window.",
    "ERR_DUPLICATE_SELLER_EMAIL": "Another seller already uses that email.",
    "ERR_DUPLICATE_POLICY_CODE": "Another policy rule already uses that code.",
    "ERR_ACTION_ALREADY_EXISTS": "The cited violation already carries a non-vacated action.",
    "ERR_APPEAL_ALREADY_EXISTS": "The enforcement action has already been appealed.",
    "ERR_POA_ALREADY_OPEN": "A plan of action for that enforcement action is already submitted.",
    "ERR_POA_REVISION_LIMIT": "The revision limit for this plan of action has been reached.",
    "ERR_LISTING_SELLER_MISMATCH": "The cited listing belongs to another seller.",
    "ERR_LISTING_REQUIRED_FOR_SCOPE": "A listing-scoped rule requires a cited listing.",
    "ERR_REPORTER_NOT_ELIGIBLE": "Only a rights owner may cite an intellectual-property rule.",
    "ERR_POA_ACTION_MISMATCH": "The cited plan of action answers another enforcement action.",
    "ERR_HOLD_ACTION_SELLER_MISMATCH": "The cited enforcement action belongs to another seller.",
    "ERR_HOLD_EXCEEDS_AVAILABLE": "The computed hold exceeds the seller's available balance.",
    "ERR_FORFEIT_EXCEEDS_HOLD": "The forfeited amount exceeds the hold's held amount.",
}
