"""Error catalog and the API exception type.

Every error_id below is taken verbatim from SCAFFOLD.yaml Table 6 (and the
matching PRD section 5 catalogue); the HTTP status is the one the catalog
assigns.  No error identifier is invented here.
"""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_BRAND_NOT_FOUND": 404,
    "ERR_LOCATION_NOT_FOUND": 404,
    "ERR_STORE_DAY_NOT_FOUND": 404,
    "ERR_ITEM_NOT_FOUND": 404,
    "ERR_CHECK_NOT_FOUND": 404,
    "ERR_RECEIPT_NOT_FOUND": 404,
    "ERR_TRANSFER_NOT_FOUND": 404,
    "ERR_SHIFT_NOT_FOUND": 404,
    "ERR_CLEARANCE_NOT_FOUND": 404,
    "ERR_PLANOGRAM_NOT_FOUND": 404,
    "ERR_STALE_VERSION": 412,
    "ERR_STORE_DAY_DUPLICATE": 409,
    "ERR_RECEIPT_DUPLICATE": 409,
    "ERR_PLANOGRAM_SLOT_CONFLICT": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STORE_DAY_CLOSED": 409,
    "ERR_STORE_DAY_GATE_SUSPENDED": 409,
    "ERR_STORE_DAY_GATE_RESTRICTED": 409,
    "ERR_CHECK_ALREADY_FINALIZED": 409,
    "ERR_FISCAL_PERIOD_CLOSED": 422,
    "ERR_BACKROOM_OVER_CAPACITY": 409,
    "ERR_FOOD_STORAGE_ZONE_FORBIDDEN": 409,
    "ERR_TRANSFER_VARIANCE_EXCEEDED": 422,
    "ERR_CROSSOVER_NOT_AUTHORIZED": 403,
    "ERR_POSTURE_LOCKOUT": 409,
    "ERR_CLEARANCE_WINDOW_OVERLAP": 409,
    "ERR_CLEARANCE_SLOT_LIMIT": 409,
    "ERR_CLEARANCE_NOT_FINAL": 409,
    "ERR_CLEARANCE_WINDOW_REACTIVATION_LIMIT": 409,
    "ERR_CHECK_TOTAL_EXCEEDED": 422,
    "ERR_CHECK_STORE_DAY_MISMATCH": 422,
    "ERR_GIFT_CARD_LINE_MISMATCH": 422,
    "ERR_TIP_INELIGIBLE_WORKCODE": 422,
    "ERR_SHIFT_OVERLAP": 409,
    "ERR_TIP_SHIFT_TOO_SHORT": 422,
    "ERR_PLANOGRAM_VERSION_CONFLICT": 409,
    "ERR_NO_REGIONAL_ASSORTMENT": 403,
}

ERROR_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-Role or X-User-ID header is absent, or the role value is not a declared role.",
    "ERR_UNAUTHORIZED": "The declared role is not permitted for this operation.",
    "ERR_INVALID_REQUEST": "The request is malformed, a required field is missing, a numeric bound is violated, or a generic type constraint failed.",
    "ERR_NOT_FOUND": "The requested resource does not exist.",
    "ERR_BRAND_NOT_FOUND": "No Brand exists for the supplied identifier.",
    "ERR_LOCATION_NOT_FOUND": "No Location exists for the supplied identifier.",
    "ERR_STORE_DAY_NOT_FOUND": "No StoreDay exists for the supplied identifier.",
    "ERR_ITEM_NOT_FOUND": "No Item exists for the supplied identifier.",
    "ERR_CHECK_NOT_FOUND": "No GuestCheck exists for the supplied identifier.",
    "ERR_RECEIPT_NOT_FOUND": "No Receipt exists for the supplied identifier.",
    "ERR_TRANSFER_NOT_FOUND": "No Transfer exists for the supplied identifier.",
    "ERR_SHIFT_NOT_FOUND": "No StaffShift exists for the supplied identifier.",
    "ERR_CLEARANCE_NOT_FOUND": "No ClearanceSchedule exists for the supplied identifier.",
    "ERR_PLANOGRAM_NOT_FOUND": "No PlanogramVersion or PlanogramSlot exists for the supplied identifier.",
    "ERR_STALE_VERSION": "The expected parent version does not match the resource's current version.",
    "ERR_STORE_DAY_DUPLICATE": "A StoreDay already exists for this (location_id, business_date).",
    "ERR_RECEIPT_DUPLICATE": "receipt_number already exists for this (location_id, business_date).",
    "ERR_PLANOGRAM_SLOT_CONFLICT": "The slot position is already taken, or the item's theme is not carried at this assortment tier.",
    "ERR_INVALID_STATE": "The resource is not in a state from which the requested operation is defined.",
    "ERR_STORE_DAY_CLOSED": "The operation targets a StoreDay whose day_status is CLOSED.",
    "ERR_STORE_DAY_GATE_SUSPENDED": "The StoreDay's conversion_gate is SUSPENDED and refuses this retail-side write.",
    "ERR_STORE_DAY_GATE_RESTRICTED": "The StoreDay's conversion_gate is GATED_RESTRICTED and refuses new backroom load.",
    "ERR_CHECK_ALREADY_FINALIZED": "The GuestCheck is already FINALIZED or VOIDED and cannot accept further retail lines.",
    "ERR_FISCAL_PERIOD_CLOSED": "Revenue recognition was attempted after the brand's fiscal period was closed.",
    "ERR_BACKROOM_OVER_CAPACITY": "Receiving would drive the location's staging_free_units below zero.",
    "ERR_FOOD_STORAGE_ZONE_FORBIDDEN": "A retail transfer is routed into the FOOD_STORAGE receiving zone.",
    "ERR_TRANSFER_VARIANCE_EXCEEDED": "The receiving variance exceeds the brand's transfer variance tolerance.",
    "ERR_CROSSOVER_NOT_AUTHORIZED": "The shift spans both labor pools without an authorizing manager shift.",
    "ERR_POSTURE_LOCKOUT": "The location's posture blocks the requested retail-side operation.",
    "ERR_CLEARANCE_WINDOW_OVERLAP": "Two clearance windows on the same (location_id, item_id) are separated by less than the clearance buffer.",
    "ERR_CLEARANCE_SLOT_LIMIT": "The location's active_clearance_count is already at its clearance_max_active.",
    "ERR_CLEARANCE_NOT_FINAL": "Liquidation was attempted before stage S4 or on an item that is not in CLEARANCE.",
    "ERR_CLEARANCE_WINDOW_REACTIVATION_LIMIT": "The clearance window has already been reactivated twice.",
    "ERR_CHECK_TOTAL_EXCEEDED": "The combined check total would exceed the brand's max_check_total_cents.",
    "ERR_CHECK_STORE_DAY_MISMATCH": "The receipt's store day differs from its attached GuestCheck's store day.",
    "ERR_GIFT_CARD_LINE_MISMATCH": "A GIFT_CARD line appears without GIFT_CARD tender, or more than once.",
    "ERR_TIP_INELIGIBLE_WORKCODE": "tip_eligible_claim is true for a workcode that is not a tip-eligible position.",
    "ERR_SHIFT_OVERLAP": "The (location_id, employee_id) pair already has a shift overlapping this interval.",
    "ERR_TIP_SHIFT_TOO_SHORT": "A tip-eligibility claim is asserted for a shift that cannot reach the tip minimum.",
    "ERR_PLANOGRAM_VERSION_CONFLICT": "The planogram version carries fewer than six slots, or a competing draft has an earlier effective_date.",
    "ERR_NO_REGIONAL_ASSORTMENT": "The item's theme is not carried by this region's assortment tier.",
}


class ApiError(Exception):
    """Carries the error_id, the message and the HTTP status to emit."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or ERROR_MESSAGE.get(error_id, error_id)
        super().__init__(self.message)


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)