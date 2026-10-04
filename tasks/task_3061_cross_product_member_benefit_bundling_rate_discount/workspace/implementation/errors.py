"""Error catalogue for the Member Benefit Bundling API (PRD section 5)."""

ERR_MISSING_AUTH_HEADERS = "ERR_MISSING_AUTH_HEADERS"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_MEMBER_NOT_FOUND = "ERR_MEMBER_NOT_FOUND"
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_HOLDING_NOT_ADOPTED = "ERR_HOLDING_NOT_ADOPTED"
ERR_CREDIT_CONDITIONING_BLOCKED = "ERR_CREDIT_CONDITIONING_BLOCKED"
ERR_REUSE_UNDERWRITING_PROHIBITED = "ERR_REUSE_UNDERWRITING_PROHIBITED"
ERR_CONSENT_REQUIRED = "ERR_CONSENT_REQUIRED"
ERR_OVERRIDE_NOT_PERMITTED = "ERR_OVERRIDE_NOT_PERMITTED"
ERR_STACK_CLASS_CONFLICT = "ERR_STACK_CLASS_CONFLICT"
ERR_DUPLICATE_DISCOUNT_APPLICATION = "ERR_DUPLICATE_DISCOUNT_APPLICATION"
ERR_RULE_WINDOW_OVERLAP = "ERR_RULE_WINDOW_OVERLAP"
ERR_DUPLICATE_RULE_CODE = "ERR_DUPLICATE_RULE_CODE"
ERR_SELF_STACK_CYCLE = "ERR_SELF_STACK_CYCLE"
ERR_BENEFIT_ALREADY_GRANTED = "ERR_BENEFIT_ALREADY_GRANTED"
ERR_DUPLICATE_ENTITLEMENT = "ERR_DUPLICATE_ENTITLEMENT"
ERR_SESSION_OVERLAP = "ERR_SESSION_OVERLAP"
ERR_ENROLLMENT_NOT_ACTIVE = "ERR_ENROLLMENT_NOT_ACTIVE"
ERR_GRACE_PERIOD_NOT_ELAPSED = "ERR_GRACE_PERIOD_NOT_ELAPSED"
ERR_REQUALIFICATION_WINDOW_OPEN = "ERR_REQUALIFICATION_WINDOW_OPEN"
ERR_INSUFFICIENT_POINTS = "ERR_INSUFFICIENT_POINTS"
ERR_REDEMPTION_LIMIT_EXCEEDED = "ERR_REDEMPTION_LIMIT_EXCEEDED"
ERR_PRINCIPAL_BELOW_ZERO = "ERR_PRINCIPAL_BELOW_ZERO"
ERR_STACK_CAP_EXCEEDED = "ERR_STACK_CAP_EXCEEDED"
ERR_HOLDING_HAS_ACTIVE_LOAN = "ERR_HOLDING_HAS_ACTIVE_LOAN"
ERR_ENTITLEMENT_NO_SOURCE_HOLDING = "ERR_ENTITLEMENT_NO_SOURCE_HOLDING"
ERR_ACTIVE_RULE_ON_UNPRICED_LOAN = "ERR_ACTIVE_RULE_ON_UNPRICED_LOAN"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_SESSION_CAPACITY_SATURATED = "ERR_SESSION_CAPACITY_SATURATED"

STATUS = {
    ERR_MISSING_AUTH_HEADERS: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_SEGREGATION_OF_DUTIES: 403,
    ERR_MEMBER_NOT_FOUND: 404,
    ERR_RESOURCE_NOT_FOUND: 404,
    ERR_STALE_VERSION: 412,
    ERR_INVALID_STATE: 409,
    ERR_HOLDING_NOT_ADOPTED: 409,
    ERR_CREDIT_CONDITIONING_BLOCKED: 422,
    ERR_REUSE_UNDERWRITING_PROHIBITED: 422,
    ERR_CONSENT_REQUIRED: 422,
    ERR_OVERRIDE_NOT_PERMITTED: 422,
    ERR_STACK_CLASS_CONFLICT: 409,
    ERR_DUPLICATE_DISCOUNT_APPLICATION: 409,
    ERR_RULE_WINDOW_OVERLAP: 409,
    ERR_DUPLICATE_RULE_CODE: 409,
    ERR_SELF_STACK_CYCLE: 422,
    ERR_BENEFIT_ALREADY_GRANTED: 409,
    ERR_DUPLICATE_ENTITLEMENT: 409,
    ERR_SESSION_OVERLAP: 409,
    ERR_ENROLLMENT_NOT_ACTIVE: 409,
    ERR_GRACE_PERIOD_NOT_ELAPSED: 409,
    ERR_REQUALIFICATION_WINDOW_OPEN: 409,
    ERR_INSUFFICIENT_POINTS: 422,
    ERR_REDEMPTION_LIMIT_EXCEEDED: 422,
    ERR_PRINCIPAL_BELOW_ZERO: 422,
    ERR_STACK_CAP_EXCEEDED: 422,
    ERR_HOLDING_HAS_ACTIVE_LOAN: 409,
    ERR_ENTITLEMENT_NO_SOURCE_HOLDING: 422,
    ERR_ACTIVE_RULE_ON_UNPRICED_LOAN: 422,
    ERR_INVALID_REQUEST: 400,
    ERR_SESSION_CAPACITY_SATURATED: 409,
}

MESSAGES = {
    ERR_MISSING_AUTH_HEADERS: "X-User-ID and X-User-Role headers are both required and must be non-empty.",
    ERR_FORBIDDEN_ROLE: "The acting role is not permitted for this operation, or the acting identity does not own the targeted resource.",
    ERR_SEGREGATION_OF_DUTIES: "The approving operator must differ from the operator who requested the override.",
    ERR_MEMBER_NOT_FOUND: "The member named in the path does not exist.",
    ERR_RESOURCE_NOT_FOUND: "The resource named in the path does not exist.",
    ERR_STALE_VERSION: "The supplied entity version is stale; the resource has advanced since it was read.",
    ERR_INVALID_STATE: "The target resource is not in a state that permits the requested transition.",
    ERR_HOLDING_NOT_ADOPTED: "The referenced holding is not adopted, so the benefit or discount cannot be priced.",
    ERR_CREDIT_CONDITIONING_BLOCKED: "Credit may not be conditioned on the purchase of a banking or investing product.",
    ERR_REUSE_UNDERWRITING_PROHIBITED: "Underwriting reuse is not permitted for this target product line.",
    ERR_CONSENT_REQUIRED: "An affirmative consent record is required before this cross-sell contact may proceed.",
    ERR_OVERRIDE_NOT_PERMITTED: "An override may only be queued by benefits administration while the override window is open.",
    ERR_STACK_CLASS_CONFLICT: "A declared stacking link must join rules of the same stacking class.",
    ERR_DUPLICATE_DISCOUNT_APPLICATION: "An applied discount application already occupies this loan and rule pair.",
    ERR_RULE_WINDOW_OVERLAP: "The rule validity window overlaps a live rule of the same kind below the minimum gap.",
    ERR_DUPLICATE_RULE_CODE: "The rule code already exists.",
    ERR_SELF_STACK_CYCLE: "The stacking chain revisits a rule.",
    ERR_BENEFIT_ALREADY_GRANTED: "The entitlement is already granted.",
    ERR_DUPLICATE_ENTITLEMENT: "A duplicate entitlement row already exists.",
    ERR_SESSION_OVERLAP: "The session collides with another non-cancelled career-coaching session on the same coach.",
    ERR_ENROLLMENT_NOT_ACTIVE: "A rule that requires direct deposit cannot be priced while the enrollment is not active.",
    ERR_GRACE_PERIOD_NOT_ELAPSED: "The enrollment may not lapse before its grace deadline.",
    ERR_REQUALIFICATION_WINDOW_OPEN: "The requalification cycle may not be evaluated before its due instant.",
    ERR_INSUFFICIENT_POINTS: "The requested redemption exceeds the member's posted points balance.",
    ERR_REDEMPTION_LIMIT_EXCEEDED: "The redemption sits outside the permitted per-entry bounds.",
    ERR_PRINCIPAL_BELOW_ZERO: "The redemption would drive the loan principal below zero.",
    ERR_STACK_CAP_EXCEEDED: "The request asks to store an uncapped discount stack above the ceiling.",
    ERR_HOLDING_HAS_ACTIVE_LOAN: "A lending holding carrying a live loan account may not be closed.",
    ERR_ENTITLEMENT_NO_SOURCE_HOLDING: "The named source holding does not exist or belongs to another member.",
    ERR_ACTIVE_RULE_ON_UNPRICED_LOAN: "The rule stacks upon a rule that is missing or still a draft.",
    ERR_INVALID_REQUEST: "The request body is malformed, incomplete, or carries a value outside its declared domain.",
    ERR_SESSION_CAPACITY_SATURATED: "The member-event capacity for this coach and interval has already been reached.",
}


class ApiError(Exception):
    """Carries the machine-readable error id and the HTTP status it maps to."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or STATUS.get(error_id, 400)
        super().__init__(self.message)