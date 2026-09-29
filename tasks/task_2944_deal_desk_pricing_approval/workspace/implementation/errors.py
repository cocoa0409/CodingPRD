"""Error catalogue (PRD section 5) and the ApiError exception."""

ERROR_STATUS = {
    # authentication and authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_QUOTE_OWNER": 403,
    "ERR_NOT_GRANT_GRANTOR": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_APPROVER_ROLE_MISMATCH": 403,
    # not found
    "ERR_DESK_POLICY_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_QUOTE_NOT_FOUND": 404,
    "ERR_QUOTE_LINE_NOT_FOUND": 404,
    "ERR_TERM_NOT_FOUND": 404,
    "ERR_EXCEPTION_NOT_FOUND": 404,
    "ERR_REVREC_NOT_FOUND": 404,
    "ERR_APPROVAL_STEP_NOT_FOUND": 404,
    "ERR_DELEGATION_NOT_FOUND": 404,
    "ERR_ORDER_FORM_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # configuration integrity
    "ERR_DUPLICATE_PRODUCT_SKU": 409,
    "ERR_APPROVAL_TIER_OVERLAP": 409,
    "ERR_VOLUME_TIER_OVERLAP": 409,
    "ERR_DUPLICATE_BUNDLE_RULE": 409,
    "ERR_APPROVAL_TIER_COVERAGE_INVALID": 422,
    # state preconditions
    "ERR_DESK_POLICY_NOT_DRAFT": 409,
    "ERR_QUOTE_NOT_DRAFT": 409,
    "ERR_QUOTE_NOT_PENDING_APPROVAL": 409,
    "ERR_QUOTE_NOT_APPROVED": 409,
    "ERR_QUOTE_NOT_CHANGES_REQUESTED": 409,
    "ERR_QUOTE_STATE_INVALID_FOR_REVOKE": 409,
    "ERR_STEP_ALREADY_DECIDED": 409,
    "ERR_TERM_ALREADY_REVIEWED": 409,
    "ERR_TERM_NOT_LEGAL_APPROVED": 409,
    "ERR_EXCEPTION_STATE_INVALID": 409,
    "ERR_REVREC_STATE_INVALID": 409,
    "ERR_ORDER_FORM_STATE_INVALID": 409,
    "ERR_DELEGATION_STATE_INVALID": 409,
    # optimistic concurrency
    "ERR_STALE_QUOTE_VERSION": 412,
    # legal review and co-signature gating
    "ERR_LEGAL_REVIEW_NOT_REQUIRED": 409,
    "ERR_TERM_COSIGN_NOT_REQUIRED": 409,
    "ERR_TERM_ALREADY_COSIGNED": 409,
    # delegation of authority
    "ERR_DELEGATION_NOT_ACTIVE": 409,
    "ERR_DELEGATION_LEVEL_NOT_DELEGABLE": 422,
    "ERR_DELEGATION_SCOPE_EXCEEDED": 422,
    "ERR_DELEGATION_WINDOW_OVERLAP": 409,
    # temporal
    "ERR_QUOTE_EXPIRED": 409,
    "ERR_PRICE_HOLD_WINDOW_CONFLICT": 409,
    # structural submit gates
    "ERR_QUOTE_HAS_NO_LINES": 422,
    "ERR_DESK_POLICY_SUPERSEDED": 422,
    "ERR_TERM_BELOW_PRODUCT_MINIMUM": 422,
    "ERR_NONSTANDARD_TERM_REQUIRED": 422,
    "ERR_REVREC_NOT_CLEARED": 422,
    # fiscal
    "ERR_NO_ACTIVE_DESK_POLICY": 422,
    "ERR_DISCOUNT_STACK_EXCEEDED": 422,
    "ERR_MARGIN_FLOOR_BREACH": 422,
    "ERR_ABSOLUTE_MARGIN_FLOOR_BREACH": 422,
    "ERR_EXCEPTION_NOT_NEEDED": 422,
    "ERR_EXCEPTION_ALLOWANCE_EXHAUSTED": 422,
    # booking
    "ERR_ACCOUNT_CREDIT_HOLD": 409,
    "ERR_BOOKING_CRITERIA_UNMET": 422,
    # generic fallback for an unrouted path
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    words = error_id[4:].replace("_", " ").lower() if error_id.startswith("ERR_") else error_id
    return "Request rejected: %s." % words


def fail(error_id, message=None):
    raise ApiError(error_id, message)
