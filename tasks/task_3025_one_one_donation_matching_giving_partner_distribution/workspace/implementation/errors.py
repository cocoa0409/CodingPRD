"""Error catalog and the exception type every route raises.

The error_id values and HTTP statuses are taken verbatim from the scaffold's
error table (Table 6) and the PRD's error catalogue (section 5).
"""


class ApiError(Exception):
    """Carries the error_id, human message and HTTP status of a rejection."""

    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status or STATUSES.get(error_id, 409)
        super().__init__(self.message)


# error_id -> HTTP status (scaffold Table 6 / PRD section 5)
STATUSES = {
    "ERR_MISSING_AUTH_CONTEXT": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_PARTNER_NOT_FOUND": 404,
    "ERR_PRODUCT_NOT_FOUND": 404,
    "ERR_DONATION_PRODUCT_LINE_NOT_FOUND": 404,
    "ERR_SALES_ORDER_NOT_FOUND": 404,
    "ERR_SALES_ORDER_LINE_NOT_FOUND": 404,
    "ERR_SEASON_NOT_FOUND": 404,
    "ERR_LIABILITY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_DISTRIBUTION_NOT_FOUND": 404,
    "ERR_AUDIT_NOT_FOUND": 404,
    "ERR_VETTING_ROUND_NOT_FOUND": 404,
    "ERR_RETURN_REQUEST_NOT_FOUND": 404,
    "ERR_CAPACITY_PROFILE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_FULFILLMENT_REGRESSION": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PARTNER_SUSPENDED": 409,
    "ERR_PARTNER_NOT_APPROVED": 409,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_CAPACITY_PROFILE_AMBIGUOUS": 409,
    "ERR_SEASON_FROZEN": 409,
    "ERR_RETURN_WINDOW_CLOSED": 422,
    "ERR_ADDON_TIER_BOUNDARY": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
    "ERR_LIABILITY_INSUFFICIENT": 409,
    "ERR_CLAIM_PERIOD_UNSUPPORTED": 409,
    "ERR_ENTITY_UNRESOLVED": 409,
    "ERR_NEED_SCORE_BELOW_MINIMUM": 409,
    "ERR_VETTING_ROUND_TERMINAL": 409,
    "ERR_PARTNER_REJECTION_FINAL": 409,
    "ERR_REGISTRY_NOT_VERIFIED": 409,
    "ERR_DESIGN_WEIGHT_BELOW_MINIMUM": 409,
    "ERR_LINE_NOT_DONATION_ELIGIBLE": 409,
    "ERR_OBLIGATION_ALREADY_VESTED": 409,
    "ERR_PARTNER_CAPACITY_LOCKED": 409,
    "ERR_ALLOCATION_NOT_REVERSIBLE": 409,
    "ERR_REVERSAL_REQUIRES_RECEIVED": 409,
    "ERR_SHIPMENT_EXCEEDS_ALLOCATION": 409,
    "ERR_RECEIPT_EXCEEDS_SHIPMENT": 409,
    "ERR_DISTRIBUTION_NOT_IN_TRANSIT": 409,
    "ERR_DISCREPANCY_NOT_RAISED": 409,
    "ERR_ZERO_SHIPPED_UNITS": 409,
    "ERR_OUTSTANDING_DISTRIBUTIONS": 409,
    "ERR_CARRY_PRECONDITION_UNMET": 409,
    "ERR_CLAIM_ALREADY_REVOKED": 409,
    "ERR_CLAIM_WINDOW_UNSUBSTANTIATED": 409,
    "ERR_AUDIT_ALREADY_FINALIZED": 409,
    "ERR_AUDIT_LOCK_NOT_RESETTABLE": 409,
    "ERR_AUDIT_SOD_VIOLATION": 403,
    "ERR_RECEIPT_SAMPLE_EXCEEDS_PLAN": 409,
    "ERR_SALES_ORDER_ALREADY_PAID": 409,
    "ERR_SALES_ORDER_CANCELLED": 409,
    "ERR_LINE_ALREADY_RETURNED": 409,
    "ERR_EXCHANGE_REPLACEMENT_INVALID": 409,
    "ERR_EXEMPTION_REASON_INVALID": 409,
    "ERR_CLOCK_ROLL_CONFLICT": 409,
    "ERR_ALLOCATION_VERSION_SUPERSEDED": 409,
    "ERR_ALLOCATION_DISTRIBUTION_EXISTS": 409,
}

MESSAGES = {
    "ERR_MISSING_AUTH_CONTEXT": "X-User-ID and X-User-Role headers are required and X-User-Role must name a recognized role.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not permitted for this operation.",
    "ERR_INVALID_REQUEST": "The request body or query parameters are malformed.",
    "ERR_INVALID_STATE_TRANSITION": "The resource is not in a state from which the requested transition is declared.",
    "ERR_FULFILLMENT_REGRESSION": "The requested fulfillment_status is not strictly later than the stored one.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the stored version.",
    "ERR_PARTNER_SUSPENDED": "The naming partner is SUSPENDED and only EMERGENCY priority allocations are permitted.",
    "ERR_PARTNER_NOT_APPROVED": "The naming partner is not APPROVED and is ineligible for a benefit allocation.",
    "ERR_DUPLICATE_RESOURCE": "A unique key already exists.",
    "ERR_CAPACITY_PROFILE_AMBIGUOUS": "More than one selectable capacity profile resolves for this partner and season.",
    "ERR_SEASON_FROZEN": "The write instant falls after the season's freezes_at or the season is FINALIZED.",
    "ERR_RETURN_WINDOW_CLOSED": "The return request falls outside the line's return window.",
    "ERR_ADDON_TIER_BOUNDARY": "The add-on tier divisor was selected on a base count that already included the surcharge.",
    "ERR_CAPACITY_EXCEEDED": "capacity_utilization_units would exceed max_allocatable_units.",
    "ERR_LIABILITY_INSUFFICIENT": "The liability's available units do not cover the allocation.",
    "ERR_CLAIM_PERIOD_UNSUPPORTED": "The claim's stated_reference_period is not a window the season covers.",
    "ERR_ENTITY_UNRESOLVED": "Referenced resources disagree on their external identity.",
}


def not_found(resource):
    """ERR_{RESOURCE}_NOT_FOUND helper."""
    return ApiError("ERR_%s_NOT_FOUND" % resource.upper())