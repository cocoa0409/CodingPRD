class APIError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="X-User-ID or X-User-Role header missing or empty"):
    return APIError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for this endpoint"):
    return APIError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced resource id does not exist"):
    return APIError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Missing or invalid required field"):
    return APIError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Entity not in a valid state for the requested transition"):
    return APIError("ERR_INVALID_STATE", 409, msg)


def err_service_level_not_available(msg="ROOM_OF_CHOICE ordered for a non white-glove-eligible item"):
    return APIError("ERR_SERVICE_LEVEL_NOT_AVAILABLE", 422, msg)


def err_item_not_listed(msg="Order references a DELISTED item or an item whose supplier is SUSPENDED"):
    return APIError("ERR_ITEM_NOT_LISTED", 409, msg)


def err_no_route(msg="No hub/lane combination can serve the destination zone for the chosen service level"):
    return APIError("ERR_NO_ROUTE", 422, msg)


def err_pricing_unavailable(msg="No ACTIVE FreightLane for the selected leg_mode and destination zone"):
    return APIError("ERR_PRICING_UNAVAILABLE", 402, msg)


def err_invalid_appointment_window(msg="Invalid appointment window"):
    return APIError("ERR_INVALID_APPOINTMENT_WINDOW", 422, msg)


def err_appointment_overlap(msg="ROOM_OF_CHOICE booking overlaps an existing BOOKED appointment on the same hub/crew"):
    return APIError("ERR_APPOINTMENT_OVERLAP", 409, msg)


def err_hub_daily_capacity_exceeded(msg="Arriving linehaul would exceed hub daily capacity for that date"):
    return APIError("ERR_HUB_DAILY_CAPACITY_EXCEEDED", 409, msg)


def err_linehaul_capacity_exceeded(msg="No PLANNED linehaul with free capacity exists for binding"):
    return APIError("ERR_LINEHAUL_CAPACITY_EXCEEDED", 409, msg)


def err_return_window_closed(msg="Approve attempted more than 45 days after delivery"):
    return APIError("ERR_RETURN_WINDOW_CLOSED", 422, msg)


def err_chargeback_open(msg="DamageClaim settle attempted while its Chargeback is PENDING or DISPUTED"):
    return APIError("ERR_CHARGEBACK_OPEN", 409, msg)


def err_stale_version(msg="expected_shipment_version does not match current Shipment version"):
    return APIError("ERR_STALE_VERSION", 412, msg)


def err_item_has_open_shipments(msg="Delist attempted while non-terminal shipments reference the item"):
    return APIError("ERR_ITEM_HAS_OPEN_SHIPMENTS", 409, msg)


def err_order_not_delivered(msg="ReturnAuthorization approve requires order_state == DELIVERED"):
    return APIError("ERR_ORDER_NOT_DELIVERED", 409, msg)


def err_claim_requires_inspectable_shipment(msg="Inspect requires shipment AT_HUB or DELIVERED"):
    return APIError("ERR_CLAIM_REQUIRES_INSPECTABLE_SHIPMENT", 409, msg)
