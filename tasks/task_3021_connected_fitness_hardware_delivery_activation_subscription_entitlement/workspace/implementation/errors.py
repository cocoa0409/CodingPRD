"""Error catalogue for the Connected Fitness Hardware API.

Every identifier, HTTP status and trigger condition comes from SCAFFOLD.yaml
section 1.6 / PRD section 5.  Nothing else is invented here.
"""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# error_id -> HTTP status (scaffold section 1.6)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_MEMBERSHIP_STALE_VERSION": 412,
    "ERR_DEVICE_STALE_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_POSTURE_RESTRICTED": 409,
    "ERR_CONCURRENT_LIMIT_EXCEEDED": 409,
    "ERR_STAIR_CAP_EXCEEDED": 409,
    "ERR_TEMPORAL_OVERLAP": 409,
    "ERR_LICENSE_WINDOW_INVALID": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_RESCHEDULE_LIMIT": 409,
    "ERR_PAUSE_WINDOW_INVALID": 409,
    "ERR_UNPAID_FINANCING_BLOCK": 409,
    "ERR_SAFETY_DISABLE_FORBIDDEN": 409,
    "ERR_PART_SKU_MISMATCH": 409,
    "ERR_PART_MISMATCH_SAFETY": 409,
    "ERR_PART_SAFETY_STOCK": 409,
    "ERR_PART_INSUFFICIENT": 409,
    "ERR_PART_REQUIRED_FOR_SCHEDULING": 409,
    "ERR_DEVICE_SERIAL_MISMATCH": 409,
    "ERR_DEVICE_NOT_ON_MEMBERSHIP": 409,
    "ERR_ORDER_MEMBERSHIP_MISMATCH": 409,
    "ERR_CERTIFYING_DEVICE_NOT_ELIGIBLE": 409,
    "ERR_CERTIFICATION_CHAIN_EXCEEDED": 409,
    "ERR_CERTIFICATION_CYCLE": 409,
    "ERR_WARRANTY_RESET_NOT_ELIGIBLE": 409,
    "ERR_CLASS_CAPACITY_EXCEEDED": 409,
    "ERR_CONTENT_LOCKED": 409,
    "ERR_OWNER_ALREADY_EXISTS": 409,
    "ERR_INSTALLMENT_COUNT_EXCEEDED": 409,
    "ERR_PLAN_ALREADY_PAID_OFF": 409,
    "ERR_REFUND_DISPUTE_DENIED": 409,
    "ERR_PURCHASE_BLOCKED": 409,
    "ERR_DISPATCH_DEVICE_NOT_OPERATIONAL": 409,
}


# Default human-readable messages.  Call sites may override with a more
# specific explanation; the identifier and status are what the tests key on.
ERROR_MESSAGES = {
    "ERR_UNAUTHENTICATED": "The X-User-ID and X-User-Role headers must both be present and the role must be a declared role.",
    "ERR_UNAUTHORIZED": "The declared role is not permitted for this operation, or the addressed resource is owned by another membership.",
    "ERR_INVALID_REQUEST": "The request payload is malformed: a required field is absent, an unknown field was supplied, or a value violates its declared type or enum domain.",
    "ERR_RESOURCE_NOT_FOUND": "The addressed resource does not exist.",
    "ERR_MEMBERSHIP_STALE_VERSION": "The supplied expected_membership_version does not match the membership's current version.",
    "ERR_DEVICE_STALE_VERSION": "The supplied expected_device_version does not match the device's current version.",
    "ERR_INVALID_STATE": "The target resource is not in a state that admits the requested transition.",
    "ERR_ALREADY_TERMINAL": "The target resource has reached a terminal state and admits no further transition.",
    "ERR_POSTURE_RESTRICTED": "The membership posture is RESTRICTED or FROZEN, so a new hardware order or financing plan is refused.",
    "ERR_CONCURRENT_LIMIT_EXCEEDED": "The stream ceiling would be breached and no non-owner member is available for eviction.",
    "ERR_STAIR_CAP_EXCEEDED": "The carry would exceed the five-flight stagger-carry safety cap.",
    "ERR_TEMPORAL_OVERLAP": "The proposed half-open window overlaps an existing open window for the same crew or instructor.",
    "ERR_LICENSE_WINDOW_INVALID": "The session window is not contained in the instructor licensing window.",
    "ERR_WINDOW_NOT_OPEN": "The logical clock sits outside the window required for this operation.",
    "ERR_RESCHEDULE_LIMIT": "The appointment has already been rescheduled four times.",
    "ERR_PAUSE_WINDOW_INVALID": "The requested pause window does not end after it starts, or exceeds 60 days.",
    "ERR_UNPAID_FINANCING_BLOCK": "The household carries a DELINQUENT or DEFAULTED financing plan.",
    "ERR_SAFETY_DISABLE_FORBIDDEN": "No request may clear safety_gate_open or set safety_disable_latched to true.",
    "ERR_PART_SKU_MISMATCH": "The part's compatible_sku differs from the device's hardware_sku.",
    "ERR_PART_MISMATCH_SAFETY": "A safety-critical fault cannot be resolved with an incompatible part.",
    "ERR_PART_SAFETY_STOCK": "The reservation would drop on_hand_qty below the part's safety stock floor.",
    "ERR_PART_INSUFFICIENT": "No compatible part is available to serve this cosmetic fault.",
    "ERR_PART_REQUIRED_FOR_SCHEDULING": "A cosmetic service order cannot be scheduled without a reserved part.",
    "ERR_DEVICE_SERIAL_MISMATCH": "The supplied serial differs from the device's registered serial.",
    "ERR_DEVICE_NOT_ON_MEMBERSHIP": "The device does not belong to the addressed membership.",
    "ERR_ORDER_MEMBERSHIP_MISMATCH": "The hardware order and the membership do not agree.",
    "ERR_CERTIFYING_DEVICE_NOT_ELIGIBLE": "The refurbishment source device is neither DECOMMISSIONED nor itself resale-originated.",
    "ERR_CERTIFICATION_CHAIN_EXCEEDED": "The certification lineage depth would exceed three hops.",
    "ERR_CERTIFICATION_CYCLE": "The certification lineage self-loops on the source device.",
    "ERR_WARRANTY_RESET_NOT_ELIGIBLE": "A resale warranty reset requires provenance_source RESALE.",
    "ERR_CLASS_CAPACITY_EXCEEDED": "The enrollment cannot be admitted: the library window is closed or the session is not publishable.",
    "ERR_CONTENT_LOCKED": "The device's content_access_allowed is false.",
    "ERR_OWNER_ALREADY_EXISTS": "A membership may hold exactly one OWNER household user.",
    "ERR_INSTALLMENT_COUNT_EXCEEDED": "The installment count is outside the term bounds.",
    "ERR_PLAN_ALREADY_PAID_OFF": "The financing plan is already settled.",
    "ERR_REFUND_DISPUTE_DENIED": "The refund dispute resolution is DENIED, so no redemptive credit may be issued.",
    "ERR_PURCHASE_BLOCKED": "The membership posture blocks this purchase.",
    "ERR_DISPATCH_DEVICE_NOT_OPERATIONAL": "The device has been decommissioned and cannot be scheduled for repair.",
}


def api_error(error_id, message=None):
    return ApiError(
        error_id,
        message or ERROR_MESSAGES.get(error_id, error_id),
        ERROR_STATUS.get(error_id, 409),
    )