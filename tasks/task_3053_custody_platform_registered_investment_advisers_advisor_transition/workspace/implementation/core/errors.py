"""Error catalogue: error id -> HTTP status, plus the ApiError carrier exception."""

# Error id -> HTTP status, read verbatim from SCAFFOLD.yaml §1.6 / PRD §5.
ERROR_STATUS = {
    "ERR_AUTHENTICATION_REQUIRED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_FIRM_FROZEN": 403,
    "ERR_ENTITLEMENT_NOT_GRANTED": 403,
    "ERR_SOD_VIOLATION": 403,
    "ERR_FIRM_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_PARENT_CHILD_MISMATCH": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_ACCOUNT_NOT_ELIGIBLE": 409,
    "ERR_MODEL_NOT_APPROVED": 409,
    "ERR_HOUSEHOLD_BILLING_HELD": 409,
    "ERR_FEED_THROTTLED": 409,
    "ERR_CUSTODY_AGREEMENT_REQUIRED": 409,
    "ERR_ENTITLEMENT_AGREEMENT_SUPERSEDED": 409,
    "ERR_ENTITLEMENT_DUPLICATE": 409,
    "ERR_FIRM_NOT_OPEN_FOR_TRADING": 409,
    "ERR_ADMIN_ACTION_OUTSTANDING": 409,
    "ERR_OPEN_ACCOUNTS_BLOCK_TERMINATION": 409,
    "ERR_MODEL_MANAGEMENT_ENTITLEMENT_REQUIRED": 409,
    "ERR_MODEL_WEIGHTS_INVALID": 422,
    "ERR_ALLOCATION_NOT_CONSISTENT": 422,
    "ERR_ALLOCATION_INCOMPLETE": 409,
    "ERR_NO_ELIGIBLE_ALLOCATION_TARGET": 409,
    "ERR_STANDING_INSTRUCTION_NOT_VERIFIED": 409,
    "ERR_STANDING_INSTRUCTION_EXPIRED": 409,
    "ERR_STANDING_LIMIT_EXCEEDED": 409,
    "ERR_AUTHORIZATION_NOTE_REQUIRED": 422,
    "ERR_VALUATION_STALE": 422,
    "ERR_VALUATION_BELOW_FLOOR": 422,
    "ERR_DUPLICATE_ALTERNATIVE_HOLDING": 409,
    "ERR_FEE_BASIS_ZERO": 409,
    "ERR_FEE_INVOICE_MISMATCH": 409,
    "ERR_CREDIT_EXCEEDS_FEE": 422,
    "ERR_LISTING_COOLDOWN": 409,
    "ERR_BILLING_PERIOD_INVALID": 422,
    "ERR_FEE_BASIS_BELOW_MINIMUM": 409,
    "ERR_EVIDENCE_ROUND_LIMIT": 409,
    "ERR_BUNDLE_NOT_SEALABLE": 409,
    "ERR_AMBIGUOUS_VALUATION_BINDING": 409,
    "ERR_DUPLICATE_VALUATION_PERIOD": 409,
    "ERR_REFERENCE_MISMATCH": 422,
    "ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE": 409,
    "ERR_INVARIANT_CHAIN_BROKEN": 409,
    "ERR_INVALID_IF_MATCH": 412,
    "ERR_IF_MATCH_REQUIRED": 428,
    "ERR_STALE_MODEL_VERSION": 412,
    "ERR_STALE_BLOCK_VERSION": 412,
    "ERR_STALE_HOUSEHOLD_VERSION": 412,
}

MESSAGES = {
    "ERR_AUTHENTICATION_REQUIRED": "Authentication required: supply X-User-ID and a valid X-User-Role.",
    "ERR_UNAUTHORIZED_ROLE": "The acting role is not authorized for this operation.",
    "ERR_FIRM_FROZEN": "The firm's posture is FROZEN; this operation is refused.",
    "ERR_ENTITLEMENT_NOT_GRANTED": "The required entitlement is not GRANTED for this firm.",
    "ERR_SOD_VIOLATION": "Segregation of duties violation: the acting user already performed the other half of this control.",
    "ERR_FIRM_NOT_FOUND": "The referenced firm does not exist.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_PARENT_CHILD_MISMATCH": "The resolved child row is not owned by the resolved parent row.",
    "ERR_INVALID_STATE": "The resource is not in a state that permits this operation.",
    "ERR_ALREADY_TERMINAL": "The resource has reached a terminal state.",
    "ERR_ACCOUNT_NOT_ELIGIBLE": "The account is not eligible for this operation.",
    "ERR_MODEL_NOT_APPROVED": "The parent model is not APPROVED or ACTIVE.",
    "ERR_HOUSEHOLD_BILLING_HELD": "The household's billing is held and cannot seed a new run.",
    "ERR_FEED_THROTTLED": "The data feed is THROTTLED.",
    "ERR_CUSTODY_AGREEMENT_REQUIRED": "A live, current executed custody agreement is required.",
    "ERR_ENTITLEMENT_AGREEMENT_SUPERSEDED": "The entitlement claims a superseded custody agreement.",
    "ERR_ENTITLEMENT_DUPLICATE": "A sibling entitlement already holds this entitlement code in GRANTED.",
    "ERR_FIRM_NOT_OPEN_FOR_TRADING": "The firm's posture is not OPEN for trading-path actions.",
    "ERR_ADMIN_ACTION_OUTSTANDING": "An unacknowledged regulator action blocks this operation.",
    "ERR_OPEN_ACCOUNTS_BLOCK_TERMINATION": "The firm still has OPEN accounts, blocking agreement termination.",
    "ERR_MODEL_MANAGEMENT_ENTITLEMENT_REQUIRED": "A MODEL_MANAGEMENT entitlement is required for this model write.",
    "ERR_MODEL_WEIGHTS_INVALID": "The model's target weights must sum to exactly 10000 basis points.",
    "ERR_ALLOCATION_NOT_CONSISTENT": "The block's requested shares or allocation ranks are not consistent.",
    "ERR_ALLOCATION_INCOMPLETE": "The block still carries an unallocated residual.",
    "ERR_NO_ELIGIBLE_ALLOCATION_TARGET": "No allocation targets an OPEN account with a non-zero executed quantity.",
    "ERR_STANDING_INSTRUCTION_NOT_VERIFIED": "The standing instruction is not VERIFIED.",
    "ERR_STANDING_INSTRUCTION_EXPIRED": "The standing instruction's round trip has reached seven days.",
    "ERR_STANDING_LIMIT_EXCEEDED": "The movement exceeds the standing instruction's remaining periodic limit.",
    "ERR_AUTHORIZATION_NOTE_REQUIRED": "A non-blank authorization note is required.",
    "ERR_VALUATION_STALE": "The valuation age exceeds 270 days.",
    "ERR_VALUATION_BELOW_FLOOR": "The stated value is below the holding's valuation floor.",
    "ERR_DUPLICATE_ALTERNATIVE_HOLDING": "The account already hosts an UNDER_REVIEW holding with the same asset name.",
    "ERR_FEE_BASIS_ZERO": "The household's fee basis is zero.",
    "ERR_FEE_INVOICE_MISMATCH": "The stated invoice differs from the recomputed net fee.",
    "ERR_CREDIT_EXCEEDS_FEE": "Issuing this credit would push the household's outstanding credits above its annual fee.",
    "ERR_LISTING_COOLDOWN": "A listing inside the account's one-hour listing window is refused.",
    "ERR_BILLING_PERIOD_INVALID": "The billing period is not well formed.",
    "ERR_FEE_BASIS_BELOW_MINIMUM": "The household's fee basis is below the 250000000-cent minimum.",
    "ERR_EVIDENCE_ROUND_LIMIT": "The evidence row has already consumed its four correction rounds.",
    "ERR_BUNDLE_NOT_SEALABLE": "The examination bundle is not in GENERATED state.",
    "ERR_AMBIGUOUS_VALUATION_BINDING": "Two alternative holdings on this account are UNDER_REVIEW.",
    "ERR_DUPLICATE_VALUATION_PERIOD": "The valuation as-of date collides with an accepted valuation for the same asset.",
    "ERR_REFERENCE_MISMATCH": "A referenced row belongs to a different firm.",
    "ERR_ONBOARDING_BATCH_NOT_DISPATCHABLE": "The batch's materialised entity is missing or in a state that blocks dispatch.",
    "ERR_INVARIANT_CHAIN_BROKEN": "A firm-scoped database invariant is BROKEN under ENFORCED enforcement.",
    "ERR_INVALID_IF_MATCH": "The supplied If-Match token does not match the row's current version.",
    "ERR_IF_MATCH_REQUIRED": "A state-changing PUT or POST must carry an If-Match header.",
    "ERR_STALE_MODEL_VERSION": "expected_model_portfolio_version does not match the model's current version.",
    "ERR_STALE_BLOCK_VERSION": "expected_block_order_version does not match the block's current version.",
    "ERR_STALE_HOUSEHOLD_VERSION": "expected_household_version does not match the household's current version.",
}


class ApiError(Exception):
    """Carries an error_id, its HTTP status and a human-readable message."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        super().__init__(self.message)

    def to_dict(self):
        return {"error_id": self.error_id, "message": self.message}


def fail(error_id, message=None):
    raise ApiError(error_id, message)