"""Error catalogue: error ids, HTTP statuses, and the transport exception."""


class ApiError(Exception):
    """Raised anywhere in the request path; rendered by the app's error handler."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else HTTP_BY_ERROR[error_id]


# error_id -> HTTP status, taken verbatim from the error catalogue (PRD section 5).
HTTP_BY_ERROR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST_BODY": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_NOT_CLAIM_OWNER": 403,
    "ERR_INSTALLER_NOT_CERTIFIED": 403,
    "ERR_COMMISSIONING_NOT_ENABLED": 403,
    "ERR_DESIGN_TOOL_NOT_ENABLED": 403,
    "ERR_CERTIFICATION_EXPIRED": 403,
    "ERR_DESIGN_NOT_APPROVED": 409,
    "ERR_DESIGN_NOT_OWNED": 403,
    "ERR_DC_AC_RATIO_EXCEEDED": 422,
    "ERR_SERIAL_ALREADY_REGISTERED": 409,
    "ERR_LOT_NOT_FOUND": 404,
    "ERR_LOT_NOT_ASSIGNED": 409,
    "ERR_WARRANTY_WINDOW_OVERLAP": 409,
    "ERR_REPLACEMENT_SERIAL_CONFLICT": 409,
    "ERR_INCOMPATIBLE_REPLACEMENT": 409,
    "ERR_NO_SUPPORTED_REPLACEMENT": 409,
    "ERR_LOT_RECALL_ACTIVE": 409,
    "ERR_REPLACEMENT_LIMIT_REACHED": 409,
    "ERR_ORDER_NOT_CHARGEABLE": 409,
    "ERR_UNIT_NOT_FAILED": 409,
    "ERR_LABOR_ALREADY_PENDING": 409,
    "ERR_CLAIM_RATE_FLOOR": 422,
    "ERR_RECONCILIATION_TOLERANCE_EXCEEDED": 422,
    "ERR_CORRECTION_PERIOD_CLOSED": 409,
    "ERR_LEVEL_UP_NOT_ELIGIBLE": 409,
    "ERR_NO_CAMPAIGN_TARGETS": 409,
    "ERR_LOT_NOT_IN_RECALL": 409,
    "ERR_ENTITLEMENT_WINDOW_OVERLAP": 409,
    "ERR_STALE_UNIT_VERSION": 412,
}

MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unparseable X-User-Role / X-User-ID headers.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST_BODY": "The request body is structurally invalid.",
    "ERR_INVALID_STATE": "The resource is not in a state that admits this transition.",
    "ERR_NOT_CLAIM_OWNER": "The acting installer is not the owner of this claim.",
    "ERR_INSTALLER_NOT_CERTIFIED": "The installer's certification_status is not ACTIVE.",
    "ERR_COMMISSIONING_NOT_ENABLED": "The installer does not hold commissioning_enabled.",
    "ERR_DESIGN_TOOL_NOT_ENABLED": "Design tool access is reserved to GOLD and PLATINUM installers.",
    "ERR_CERTIFICATION_EXPIRED": "The installer's certified_until instant is not strictly after the logical clock.",
    "ERR_DESIGN_NOT_APPROVED": "The referenced design project is not in APPROVED status.",
    "ERR_DESIGN_NOT_OWNED": "The referenced design project belongs to a different installer.",
    "ERR_DC_AC_RATIO_EXCEEDED": "The design's dc_ac_ratio exceeds the permitted maximum.",
    "ERR_SERIAL_ALREADY_REGISTERED": "A serial number in the payload is already registered.",
    "ERR_LOT_NOT_FOUND": "A production_lot_code in the payload resolves to no ProductionLot.",
    "ERR_LOT_NOT_ASSIGNED": "A production_lot_code is outside the design project's owner allow-list.",
    "ERR_WARRANTY_WINDOW_OVERLAP": "The proposed coverage window overlaps a live coverage window at this site.",
    "ERR_REPLACEMENT_SERIAL_CONFLICT": "The replacement serial is already installed on the target system.",
    "ERR_INCOMPATIBLE_REPLACEMENT": "The replacement model is incompatible with the replaced generation.",
    "ERR_NO_SUPPORTED_REPLACEMENT": "No replacement model can be resolved for this unit.",
    "ERR_LOT_RECALL_ACTIVE": "The unit's lot is in RECALL; the campaign pipeline must be used.",
    "ERR_REPLACEMENT_LIMIT_REACHED": "The system has no unscheduled replacement position left.",
    "ERR_ORDER_NOT_CHARGEABLE": "The order is not chargeable: source or duplicate conflict.",
    "ERR_UNIT_NOT_FAILED": "The unit's monitored_status is not FAILED.",
    "ERR_LABOR_ALREADY_PENDING": "The claim already has a LaborReimbursement in PENDING status.",
    "ERR_CLAIM_RATE_FLOOR": "The installer's claim_approval_rate_pct is not strictly above the floor.",
    "ERR_RECONCILIATION_TOLERANCE_EXCEEDED": "The billing correction variance exceeds the tolerance.",
    "ERR_CORRECTION_PERIOD_CLOSED": "The month being corrected is not strictly before the current month.",
    "ERR_LEVEL_UP_NOT_ELIGIBLE": "The level change skips a rung or the claim history is insufficient.",
    "ERR_NO_CAMPAIGN_TARGETS": "The campaign's eligible unit pool is empty.",
    "ERR_LOT_NOT_IN_RECALL": "The source lot's lot_status is not RECALL.",
    "ERR_ENTITLEMENT_WINDOW_OVERLAP": "The entitlement window overlaps an existing window on this unit.",
    "ERR_STALE_UNIT_VERSION": "The supplied expected_unit_version does not match the unit's version.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message or MESSAGES.get(error_id, error_id))