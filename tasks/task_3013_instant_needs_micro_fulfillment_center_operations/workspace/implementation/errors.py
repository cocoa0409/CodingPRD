"""Error classes: each carries the scaffold error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- auth ---
def err_unauthenticated(msg="X-User-Role header missing or malformed, or X-User-ID missing for an entity-backed role"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="Role not permitted for the endpoint, or the caller does not own the resource"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


# --- request shape ---
def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


# --- existence ---
def err_site_not_found():
    return ApiError("ERR_SITE_NOT_FOUND", "site not found", 404)


def err_product_not_found():
    return ApiError("ERR_PRODUCT_NOT_FOUND", "product not found", 404)


def err_customer_not_found():
    return ApiError("ERR_CUSTOMER_NOT_FOUND", "customer not found", 404)


def err_order_not_found():
    return ApiError("ERR_ORDER_NOT_FOUND", "order not found", 404)


def err_pick_batch_not_found():
    return ApiError("ERR_PICK_BATCH_NOT_FOUND", "pick batch not found", 404)


def err_picker_not_found():
    return ApiError("ERR_PICKER_NOT_FOUND", "picker not found", 404)


def err_driver_not_found():
    return ApiError("ERR_DRIVER_NOT_FOUND", "driver not found", 404)


def err_delivery_bag_not_found():
    return ApiError("ERR_DELIVERY_BAG_NOT_FOUND", "delivery bag not found", 404)


def err_replenish_order_not_found():
    return ApiError("ERR_REPLENISH_ORDER_NOT_FOUND", "replenish order not found", 404)


def err_stock_lot_not_found():
    return ApiError("ERR_STOCK_LOT_NOT_FOUND", "stock lot not found", 404)


def err_membership_not_found():
    return ApiError("ERR_MEMBERSHIP_NOT_FOUND", "membership not found", 404)


# --- state ---
def err_invalid_state(msg="Invalid state transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_site_not_operating():
    return ApiError("ERR_SITE_NOT_OPERATING", "Site effective_status is not OPERATING", 409)


def err_site_busy():
    return ApiError("ERR_SITE_BUSY", "Suspend requested while open batches or in-flight orders exist at the site", 409)


def err_delivery_radius_exceeded():
    return ApiError("ERR_DELIVERY_RADIUS_EXCEEDED", "delivery_distance_miles exceeds the site's delivery_radius_miles", 422)


def err_age_verification_required():
    return ApiError("ERR_AGE_VERIFICATION_REQUIRED", "Age-restricted content but the recipient is under 21 at the logical clock", 422)


def err_self_seal_forbidden():
    return ApiError("ERR_SELF_SEAL_FORBIDDEN", "Batch sealer is the same picker who owns the batch", 403)


def err_batch_full():
    return ApiError("ERR_BATCH_FULL", "Appending would exceed batch_max_lines or batch_max_items", 409)


def err_batch_empty():
    return ApiError("ERR_BATCH_EMPTY", "Seal requested on a batch with no orders", 409)


def err_product_unsellable():
    return ApiError("ERR_PRODUCT_UNSELLABLE", "Product RETIRED, or a perishable line lacks sufficient FRESH-lot cover", 422)


def err_insufficient_stock():
    return ApiError("ERR_INSUFFICIENT_STOCK", "on_hand - reserved is below a requested line quantity", 422)


def err_product_in_use():
    return ApiError("ERR_PRODUCT_IN_USE", "Retire requested while an in-flight order references the product", 409)


def err_stale_version():
    return ApiError("ERR_STALE_VERSION", "expected version does not match the entity's current version", 412)


def err_duplicate_resource(msg="Uniqueness violation"):
    return ApiError("ERR_DUPLICATE_RESOURCE", msg, 409)


def err_no_driver_available():
    return ApiError("ERR_NO_DRIVER_AVAILABLE", "Dispatch selector found no AVAILABLE driver with remaining run capacity", 409)


def err_bag_not_assigned():
    return ApiError("ERR_BAG_NOT_ASSIGNED", "depart requires delivery_status ASSIGNED", 409)


def err_handoff_not_verified():
    return ApiError("ERR_HANDOFF_NOT_VERIFIED", "Age-restricted order departing without handoff_status AGE_VERIFIED", 409)


def err_handoff_not_required():
    return ApiError("ERR_HANDOFF_NOT_REQUIRED", "handoff-scan on an order with no age-restricted lines", 409)


def err_refusal_required():
    return ApiError("ERR_REFUSAL_REQUIRED", "fail-handoff requires handoff_status REFUSED", 409)


def err_shrink_exceeds_lot():
    return ApiError("ERR_SHRINK_EXCEEDS_LOT", "SHRINK_DISPOSE qty exceeds the lot's remaining_qty, or the lot is not EXPIRED", 422)
