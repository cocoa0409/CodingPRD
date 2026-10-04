"""Error classes and error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


# Convenience constructors for the common not-found family.
def not_found(resource, id_value=None):
    mid = {
        "AIRPORT": "ERR_AIRPORT_NOT_FOUND",
        "AGREEMENT": "ERR_AGREEMENT_NOT_FOUND",
        "LANE": "ERR_LANE_NOT_FOUND",
        "KIOSK": "ERR_KIOSK_NOT_FOUND",
        "ENROLLMENT_CENTER": "ERR_ENROLLMENT_CENTER_NOT_FOUND",
        "AMBASSADOR": "ERR_AMBASSADOR_NOT_FOUND",
        "MEMBER": "ERR_MEMBER_NOT_FOUND",
        "ENROLLMENT": "ERR_ENROLLMENT_NOT_FOUND",
        "SUBSCRIPTION": "ERR_SUBSCRIPTION_NOT_FOUND",
        "INVOICE": "ERR_INVOICE_NOT_FOUND",
        "FAMILY_GROUP": "ERR_FAMILY_GROUP_NOT_FOUND",
        "DISCOUNT": "ERR_DISCOUNT_NOT_FOUND",
        "LANE_VERIFICATION": "ERR_LANE_VERIFICATION_NOT_FOUND",
        "VENUE": "ERR_VENUE_NOT_FOUND",
        "VENUE_EVENT": "ERR_VENUE_EVENT_NOT_FOUND",
        "DISPUTE": "ERR_DISPUTE_NOT_FOUND",
        "SETTLEMENT": "ERR_SETTLEMENT_NOT_FOUND",
    }[resource]
    label = resource.replace("_", " ").title()
    msg = f"{label} not found" + (f": {id_value}" if id_value else "")
    return ApiError(mid, 404, msg)


def validation(message):
    return ApiError("ERR_VALIDATION", 400, message)


def invalid_state(message):
    return ApiError("ERR_INVALID_STATE", 409, message)
