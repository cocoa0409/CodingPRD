"""Error catalogue for the Convenience Franchise Gross-Profit Split API."""


class ApiError(Exception):
    """An error carrying the scaffold's error_id / message / http_status."""

    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


_CATALOG = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STALE_VERSION": 412,
    "ERR_FRANCHISEE_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DRAW_EXCEEDS_LIMIT": 409,
    "ERR_WINDOW_CAPACITY_EXCEEDED": 409,
    "ERR_WINDOW_LOCKED": 409,
    "ERR_WINDOW_NOT_LOCKED": 409,
    "ERR_COLD_CHAIN_BROKEN": 409,
    "ERR_VENDOR_NOT_RECOMMENDED": 409,
    "ERR_AUDIT_PERIOD_NOT_CLOSED": 409,
    "ERR_AUDIT_CADENCE_REQUIRED": 409,
    "ERR_AUDIT_PERIOD_OVERLAP": 409,
    "ERR_UNFINALIZED_SHRINK_AUDIT": 409,
    "ERR_UNRECONCILED_FRESH_ORDER": 409,
    "ERR_TRANSFER_CONFLICT": 409,
    "ERR_TRANSFER_NET_WORTH_INSUFFICIENT": 409,
    "ERR_TRANSFEREE_NOT_ELIGIBLE": 409,
    "ERR_MIN_NET_WORTH_NOT_MET": 409,
    "ERR_RENEWAL_NET_WORTH_INSUFFICIENT": 409,
    "ERR_RENEWAL_WINDOW_NOT_OPEN": 409,
    "ERR_RENEWAL_ELIGIBILITY_FAILED": 409,
    "ERR_OPEN_DISPUTE_BLOCKS_RENEWAL": 409,
    "ERR_NO_OPEN_AGREEMENT": 409,
    "ERR_DRAW_PARTIALLY_RECOVERED": 409,
    "ERR_SETTLEMENT_ALREADY_FINALIZED": 409,
    "ERR_REBATE_RETRACTION_WINDOW_CLOSED": 409,
    "ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED": 409,
    "ERR_DELIVERY_OUTSIDE_WINDOW": 409,
    "ERR_WINDOW_LOCK_TOO_LATE": 409,
    "ERR_ORDER_CANCEL_WINDOW_CLOSED": 409,
    "ERR_STORE_NOT_ACTIVE": 409,
    "ERR_NO_REVENUE_LINES": 409,
    "ERR_VENDOR_REBATE_DUPLICATE": 409,
    "ERR_STORE_NUMBER_DUPLICATE": 409,
    "ERR_WINDOW_HANDLING_OVERLAP": 409,
    "ERR_SHRINK_OVERAGE_NOT_CHARGEABLE": 409,
}

ROLES = ("FranchisorAdmin", "Franchisee", "FieldAuditor", "Commissary")

_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-Role header is missing or does not name a declared role.",
    "ERR_FORBIDDEN": "The acting role is not permitted for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting franchisee does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request payload is malformed.",
    "ERR_STALE_VERSION": "The supplied expected version does not match the parent's current version.",
    "ERR_FRANCHISEE_NOT_FOUND": "franchisee_id references no Franchisee.",
    "ERR_STORE_NOT_FOUND": "store_id references no Store.",
    "ERR_RESOURCE_NOT_FOUND": "A path-segment id resolves to no resource of the expected type.",
    "ERR_INVALID_STATE": "The target resource is not in the from-state of the transition this endpoint drives.",
    "ERR_DRAW_EXCEEDS_LIMIT": "The operation would breach the operator's draw ceiling.",
    "ERR_WINDOW_CAPACITY_EXCEEDED": "The booking exceeds the delivery window's capacity.",
    "ERR_WINDOW_LOCKED": "The bound delivery window is locked or not scheduled.",
    "ERR_WINDOW_NOT_LOCKED": "A delivery was recorded against a window that is not locked.",
    "ERR_COLD_CHAIN_BROKEN": "The ordering store is not cold-chain certified.",
    "ERR_VENDOR_NOT_RECOMMENDED": "A rebate from a non-recommended vendor was presented for application.",
    "ERR_AUDIT_PERIOD_NOT_CLOSED": "The logical clock has not reached the audit's period end.",
    "ERR_AUDIT_CADENCE_REQUIRED": "The audit breaks the 31-day counting cadence.",
    "ERR_AUDIT_PERIOD_OVERLAP": "The audit period overlaps an existing non-cancelled audit.",
    "ERR_UNFINALIZED_SHRINK_AUDIT": "An overlapping shrink audit is not finalized.",
    "ERR_UNRECONCILED_FRESH_ORDER": "An overlapping fresh order is neither reconciled nor cancelled.",
    "ERR_TRANSFER_CONFLICT": "The transferee already holds an agreement on the store, or is the current operator.",
    "ERR_TRANSFER_NET_WORTH_INSUFFICIENT": "The transferee's audit-adjusted net worth is below the required floor.",
    "ERR_TRANSFEREE_NOT_ELIGIBLE": "The proposed transferee does not exist or is not ACTIVE.",
    "ERR_MIN_NET_WORTH_NOT_MET": "The operator's net worth is below the required floor.",
    "ERR_RENEWAL_NET_WORTH_INSUFFICIENT": "The operator's net worth is below the required renewal band.",
    "ERR_RENEWAL_WINDOW_NOT_OPEN": "The renewal window has not opened yet.",
    "ERR_RENEWAL_ELIGIBILITY_FAILED": "The renewal eligibility score is below 60.",
    "ERR_OPEN_DISPUTE_BLOCKS_RENEWAL": "A settlement for the store is in DISPUTED status.",
    "ERR_NO_OPEN_AGREEMENT": "The store has no agreement in ACTIVE or RENEWAL_PENDING status.",
    "ERR_DRAW_PARTIALLY_RECOVERED": "A draw with a recovered balance cannot be reversed.",
    "ERR_SETTLEMENT_ALREADY_FINALIZED": "The covering settlement is already FINALIZED.",
    "ERR_REBATE_RETRACTION_WINDOW_CLOSED": "The logical clock has not reached the rebate period end.",
    "ERR_SETTLEMENT_COOLOFF_NOT_ELAPSED": "The settlement cooling-off or dispute window did not permit this call.",
    "ERR_DELIVERY_OUTSIDE_WINDOW": "The delivery falls outside the bound window.",
    "ERR_WINDOW_LOCK_TOO_LATE": "The window is inside the 24 hours before its start.",
    "ERR_ORDER_CANCEL_WINDOW_CLOSED": "The fresh order was cancelled after its cut-off.",
    "ERR_STORE_NOT_ACTIVE": "The covering store is not ACTIVE.",
    "ERR_NO_REVENUE_LINES": "The settlement has no revenue line covering its period.",
    "ERR_VENDOR_REBATE_DUPLICATE": "A rebate already exists for this store, vendor code and period start.",
    "ERR_STORE_NUMBER_DUPLICATE": "store_number is already used by another store.",
    "ERR_WINDOW_HANDLING_OVERLAP": "The new window starts inside the handling buffer of an existing window.",
    "ERR_SHRINK_OVERAGE_NOT_CHARGEABLE": "The operator carries an unrecovered finalized shrink charge.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message or _MESSAGES.get(error_id, error_id), _CATALOG[error_id])