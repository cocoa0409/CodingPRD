"""Error catalogue and exception type.

Every error id below is taken verbatim from SCAFFOLD.yaml Table 6 / PRD.md §5,
together with its HTTP status.  Nothing here is invented.
"""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.http_status = http_status or HTTP_BY_ERROR.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "The request could not be completed."
        )
        super().__init__(self.message)


# error_id -> HTTP status (SCAFFOLD Table 6)
HTTP_BY_ERROR = {
    # authentication / authorization
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_STALE_VERSION": 412,
    # not found
    "ERR_RESOURCE_NOT_FOUND": 404,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    "ERR_REJECTION_REASON_INVALID": 400,
    "ERR_APPEAL_WINDOW_CLOSED": 400,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_BATCH_NOT_RECALLABLE": 409,
    "ERR_BATCH_ALREADY_EXPIRED": 409,
    "ERR_WINDOW_NOT_OPEN": 409,
    "ERR_WINDOW_STILL_OPEN": 409,
    "ERR_WINDOW_CLOSED": 409,
    "ERR_ENTITLEMENT_NOT_ACCEPTING": 409,
    "ERR_ORDER_NOT_ACCEPTED": 409,
    "ERR_SHIPPER_NOT_SEALED": 409,
    "ERR_SHIPPER_NOT_RELEASED": 409,
    "ERR_HOLD_NOT_CLEARED": 409,
    "ERR_CARTON_IN_TRANSIT": 409,
    "ERR_ALREADY_PUNCTURED": 409,
    "ERR_RESERVATION_EXPIRED": 409,
    "ERR_RESERVATION_ALREADY_CONFIRMED": 409,
    "ERR_APPEAL_NOT_FILED": 409,
    "ERR_APPEAL_ALREADY_OPEN": 409,
    "ERR_STORAGE_RESERVATION_CONFLICT": 409,
    "ERR_REVERSAL_DRIFT_DETECTED": 409,
    "ERR_TRANSFER_RESERVATION_ACTIVE": 409,
    "ERR_SHIPPER_HOLD": 409,
    # business safety / constraint / temporal / referential (422)
    "ERR_REFREEZE_PROHIBITED": 422,
    "ERR_REFREEZE_FORBIDDEN": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_SITE_EQUIPMENT_NOT_CERTIFIED": 422,
    "ERR_HUB_NOT_CERTIFIED": 422,
    "ERR_DEST_EQUIPMENT_NOT_CERTIFIED": 422,
    "ERR_DEST_CERT_EXPIRED_AT_DOCK": 422,
    "ERR_DEST_CAPABILITY_MISMATCH": 422,
    "ERR_DEST_RESTRICTED": 422,
    "ERR_SITE_CANNOT_ACCEPT_ULTRA_COLD": 422,
    "ERR_SLICE_NOT_CLOSED": 422,
    "ERR_SITE_FROZEN": 422,
    "ERR_EXCURSION_PENDING_REVIEW": 422,
    "ERR_PENDING_EXCURSION": 422,
    "ERR_EXCURSION_NOT_ADJUDICATED": 422,
    "ERR_EXCURSION_EXCEEDS_CAP": 422,
    "ERR_DRY_ICE_INSUFFICIENT": 422,
    "ERR_LOGGER_MISSING": 422,
    "ERR_PACKING_EXCEEDED": 422,
    "ERR_LOGGER_READING_MISSING": 422,
    "ERR_LOGGER_READING_LATE": 422,
    "ERR_DOCK_REJECTION_REQUIRED": 422,
    "ERR_SITE_CAPACITY_INSUFFICIENT": 422,
    "ERR_BELOW_MIN_ORDER": 422,
    "ERR_ENTITLEMENT_EXHAUSTED": 422,
    "ERR_ORDER_EXCEEDS_ENTITLEMENT": 422,
    "ERR_CARTON_EXPIRED": 422,
    "ERR_THAW_WINDOW_EXPIRED": 422,
    "ERR_CARTON_POST_THAW": 422,
    "ERR_CARTON_NOT_IN_USE": 422,
    "ERR_CARTON_DESTROYED": 422,
    "ERR_CARTONS_DESTROYED": 422,
    "ERR_DOSES_ALREADY_ADMINISTERED": 422,
    "ERR_DOSE_ACCOUNTABILITY_MISMATCH": 422,
    "ERR_WASTAGE_THRESHOLD_EXCEEDED": 422,
    "ERR_TRANSFER_NOT_ADJUDICATED": 422,
    "ERR_NO_HUB_AVAILABLE": 422,
    "ERR_NO_ELIGIBLE_SITE": 422,
    "ERR_SITE_NOT_READY": 422,
    "ERR_PROGRAM_NOT_OPEN": 422,
    "ERR_PROGRAM_RESTRICTED": 422,
    "ERR_PROGRAM_FROZEN": 422,
    "ERR_SITE_RESTRICTED": 422,
    "ERR_PENDING_ADJUDICATIONS_IN_PERIOD": 422,
    "ERR_PENDING_LAPSE_RECONCILIATION": 422,
    "ERR_DOSE_ACCOUNTABILITY_MISMATCH_2": 422,
    "ERR_REFERENCE_INVALID_AT_ADJUDICATION": 422,
    "ERR_ADJUDICATION_SLA_EXCEEDED": 422,
    "ERR_OUTSIDE_SHIPPING_SCHEDULE": 422,
    "ERR_PAYMENT_HOLD": 402,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER":
        "X-User-ID and X-User-Role headers must be present, well formed and name a known role.",
    "ERR_INSUFFICIENT_PERMISSIONS":
        "The acting role does not hold this operation.",
    "ERR_STALE_VERSION":
        "The supplied expected version does not match the parent's current version.",
    "ERR_RESOURCE_NOT_FOUND": "The referenced resource does not exist.",
    "ERR_INVALID_REQUEST": "The request body is malformed or carries an invalid value.",
    "ERR_INVALID_STATE": "The resource is not in a state that admits this operation.",
    "ERR_ALREADY_TERMINAL": "The resource is already in a terminal state.",
}