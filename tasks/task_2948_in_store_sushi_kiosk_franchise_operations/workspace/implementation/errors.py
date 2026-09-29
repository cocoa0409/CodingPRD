"""Error catalogue -- PRD section 5, with the rejection ladder of PRD 2.6.

The ladder rung is recorded for documentation only; the routes call the checks in
ladder order explicitly.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super(ApiError, self).__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


# PRD section 5: error_id -> HTTP status code.
HTTP_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_OWNERSHIP_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    # schema
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_HOST_STORE_NOT_FOUND": 404,
    "ERR_LICENSE_AGREEMENT_NOT_FOUND": 404,
    "ERR_KIOSK_NOT_FOUND": 404,
    "ERR_CHEF_RECORD_NOT_FOUND": 404,
    "ERR_PRODUCTION_RECORD_NOT_FOUND": 404,
    "ERR_SOURCING_RECORD_NOT_FOUND": 404,
    "ERR_SETTLEMENT_RECORD_NOT_FOUND": 404,
    "ERR_AUDIT_RECORD_NOT_FOUND": 404,
    # state
    "ERR_LICENSE_INVALID_STATE": 409,
    "ERR_KIOSK_INVALID_STATE": 409,
    "ERR_CHEF_INVALID_STATE": 409,
    "ERR_CERTIFICATION_INVALID_STATE": 409,
    "ERR_PLAN_INVALID_STATE": 409,
    "ERR_RICE_BATCH_INVALID_STATE": 409,
    "ERR_FISH_LOT_INVALID_STATE": 409,
    "ERR_PACK_LOT_INVALID_STATE": 409,
    "ERR_POS_FEED_INVALID_STATE": 409,
    "ERR_SETTLEMENT_INVALID_STATE": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    "ERR_FINDING_INVALID_STATE": 409,
    # optimistic concurrency
    "ERR_STALE_KIOSK_VERSION": 412,
    "ERR_STALE_LICENSE_VERSION": 412,
    # food safety
    "ERR_CHEF_NOT_CERTIFIED": 422,
    "ERR_HACCP_CERT_EXPIRED": 422,
    "ERR_RICE_BATCH_NOT_APPROVED": 422,
    "ERR_VARIANCE_PH_ABOVE_CEILING": 422,
    "ERR_PARASITE_DESTRUCTION_INCOMPLETE": 422,
    "ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE": 422,
    "ERR_KIOSK_POSTURE_LOCKDOWN": 422,
    "ERR_FISH_LOT_NOT_RELEASED": 422,
    # temporal windows
    "ERR_ACIDIFICATION_WINDOW_OVERLAP": 422,
    "ERR_PLAN_DATE_OUTSIDE_AGREEMENT": 422,
    "ERR_SETTLEMENT_PERIOD_OVERLAP": 422,
    "ERR_AUDIT_NOT_YET_DUE": 422,
    "ERR_PACK_SHELF_LIFE_EXPIRED": 422,
    # referential coherence
    "ERR_CROSS_KIOSK_REFERENCE": 422,
    "ERR_PERIOD_FEED_NOT_RECONCILED": 422,
    "ERR_POS_NOT_CONNECTED": 422,
    # capacity and cardinality
    "ERR_RICE_YIELD_EXCEEDED": 422,
    "ERR_PACK_CAP_EXCEEDED": 422,
    "ERR_CASE_CAPACITY_EXCEEDED": 422,
    "ERR_DUPLICATE_FEED_FOR_DATE": 422,
    "ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION": 422,
    "ERR_FINDING_NOT_WAIVABLE": 422,
    "ERR_CORRECTIVE_ROUNDS_EXHAUSTED": 422,
    # fiscal gates
    "ERR_NO_SETTLEABLE_SALES": 422,
    "ERR_PAYMENT_AMOUNT_MISMATCH": 422,
    "ERR_INSUFFICIENT_FISH_INVENTORY": 422,
    "ERR_SPACE_OBLIGATION_DEFICIENT": 422,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Both X-User-ID and X-User-Role must be present and non-empty.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this endpoint.",
    "ERR_OWNERSHIP_MISMATCH": "The acting identity does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids the same user from performing both steps.",
    "ERR_INVALID_REQUEST": "The request body or query string failed schema validation.",
    "ERR_HOST_STORE_NOT_FOUND": "The referenced host store does not exist.",
    "ERR_LICENSE_AGREEMENT_NOT_FOUND": "The referenced license agreement does not exist.",
    "ERR_KIOSK_NOT_FOUND": "The referenced kiosk does not exist.",
    "ERR_CHEF_RECORD_NOT_FOUND": "The referenced chef or certification does not exist.",
    "ERR_PRODUCTION_RECORD_NOT_FOUND": "The referenced production plan, rice batch or pack lot does not exist.",
    "ERR_SOURCING_RECORD_NOT_FOUND": "The referenced fish lot or cold-chain reading does not exist.",
    "ERR_SETTLEMENT_RECORD_NOT_FOUND": "The referenced POS sales feed or settlement statement does not exist.",
    "ERR_AUDIT_RECORD_NOT_FOUND": "The referenced audit or finding does not exist.",
    "ERR_LICENSE_INVALID_STATE": "The license agreement is not in a state that allows this transition.",
    "ERR_KIOSK_INVALID_STATE": "The kiosk is not in a state that allows this transition.",
    "ERR_CHEF_INVALID_STATE": "The chef is not in a state that allows this transition.",
    "ERR_CERTIFICATION_INVALID_STATE": "The certification is not in a state that allows this transition.",
    "ERR_PLAN_INVALID_STATE": "The production plan is not in a state that allows this transition.",
    "ERR_RICE_BATCH_INVALID_STATE": "The rice batch is not in a state that allows this transition.",
    "ERR_FISH_LOT_INVALID_STATE": "The fish lot is not in a state that allows this transition.",
    "ERR_PACK_LOT_INVALID_STATE": "The pack lot is not in a state that allows this transition.",
    "ERR_POS_FEED_INVALID_STATE": "The POS sales feed is not in a state that allows this transition.",
    "ERR_SETTLEMENT_INVALID_STATE": "The settlement statement is not in a state that allows this transition.",
    "ERR_AUDIT_INVALID_STATE": "The audit is not in a state that allows this transition.",
    "ERR_FINDING_INVALID_STATE": "The finding is not in a state that allows this transition.",
    "ERR_STALE_KIOSK_VERSION": "The echoed kiosk version does not match the kiosk's current version.",
    "ERR_STALE_LICENSE_VERSION": "The echoed license agreement version does not match the current version.",
    "ERR_CHEF_NOT_CERTIFIED": "The chef is not CERTIFIED for this operation.",
    "ERR_HACCP_CERT_EXPIRED": "A valid HACCP_RICE_ACIDIFICATION certification is required.",
    "ERR_RICE_BATCH_NOT_APPROVED": "The rice batch is not approved for pack production.",
    "ERR_VARIANCE_PH_ABOVE_CEILING": "The documented variance falls outside the documentable band.",
    "ERR_PARASITE_DESTRUCTION_INCOMPLETE": "Parasite destruction has not been satisfied for this lot.",
    "ERR_COLD_CHAIN_BREACH_BLOCKS_RELEASE": "The lot's cold-chain breach blocks release.",
    "ERR_KIOSK_POSTURE_LOCKDOWN": "The kiosk's sanitation posture is LOCKDOWN.",
    "ERR_FISH_LOT_NOT_RELEASED": "The fish lot is not RELEASED.",
    "ERR_ACIDIFICATION_WINDOW_OVERLAP": "The acidification hold window overlaps another live batch on this kiosk.",
    "ERR_PLAN_DATE_OUTSIDE_AGREEMENT": "The production date falls outside the license agreement term.",
    "ERR_SETTLEMENT_PERIOD_OVERLAP": "The settlement period overlaps another live statement of this agreement.",
    "ERR_AUDIT_NOT_YET_DUE": "The audit cannot be started before its scheduled date.",
    "ERR_PACK_SHELF_LIFE_EXPIRED": "The pack lot's shelf life has expired.",
    "ERR_CROSS_KIOSK_REFERENCE": "The referenced records do not belong to the same kiosk or host store.",
    "ERR_PERIOD_FEED_NOT_RECONCILED": "Every POS sales feed for the period must be terminal first.",
    "ERR_POS_NOT_CONNECTED": "The host store's POS integration is not CONNECTED.",
    "ERR_RICE_YIELD_EXCEEDED": "The requested pack count exceeds the rice batch's maximum yield.",
    "ERR_PACK_CAP_EXCEEDED": "The pack count exceeds the applicable pack cap.",
    "ERR_CASE_CAPACITY_EXCEEDED": "The refrigerated case capacity of the host store would be exceeded.",
    "ERR_DUPLICATE_FEED_FOR_DATE": "A live POS sales feed already exists for this store and business date.",
    "ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION": "Every finding must be corrected or waived before reverification.",
    "ERR_FINDING_NOT_WAIVABLE": "Only MINOR findings may be waived.",
    "ERR_CORRECTIVE_ROUNDS_EXHAUSTED": "The corrective round budget has been exhausted.",
    "ERR_NO_SETTLEABLE_SALES": "There are no reconciled sales in the settlement period.",
    "ERR_PAYMENT_AMOUNT_MISMATCH": "The payment amount must equal net_due_cents exactly.",
    "ERR_INSUFFICIENT_FISH_INVENTORY": "The source fish lot does not have enough remaining mass.",
    "ERR_SPACE_OBLIGATION_DEFICIENT": "The host store's dedicated space obligation is not satisfied.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message)
