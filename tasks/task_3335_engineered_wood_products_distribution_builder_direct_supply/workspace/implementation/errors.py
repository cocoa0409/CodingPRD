"""Error catalog: error_id -> (http_status, default message)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_context(msg="X-User-ID or X-User-Role header missing, or role not declared"):
    return ApiError("ERR_MISSING_OR_INVALID_CONTEXT_HEADER", msg, 400)


def err_forbidden(msg="Role not permitted for this endpoint, or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Missing required field, malformed value, or unknown enum"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_invalid_state(msg="Transition not valid for current state"):
    return ApiError("ERR_INVALID_STATE", msg, 400)


def err_quote_expired(msg="Quote has expired"):
    return ApiError("ERR_QUOTE_EXPIRED", msg, 400)


def err_delivery_window_outside_shift(msg="Delivery window outside shift window"):
    return ApiError("ERR_DELIVERY_WINDOW_OUTSIDE_SHIFT", msg, 400)


def err_jobsite_access(msg="Delivery window outside jobsite access window"):
    return ApiError("ERR_JOBSITE_ACCESS_WINDOW_VIOLATION", msg, 400)


def err_truck_shift_overlap(msg="Delivery window overlaps another delivery within 45-minute buffer"):
    return ApiError("ERR_TRUCK_SHIFT_OVERLAP", msg, 409)


def err_lien_deadline(msg="Lien filing deadline has passed"):
    return ApiError("ERR_LIEN_DEADLINE_PASSED", msg, 400)


def err_code_report_required(msg="code_report_reference required for a line product"):
    return ApiError("ERR_CODE_REPORT_REQUIRED", msg, 400)


def err_capacity_exceeded(msg="internal_alloc_mbf + market_alloc_mbf exceeds total_capacity_mbf"):
    return ApiError("ERR_CAPACITY_EXCEEDED", msg, 409)


def err_price_index_missing(msg="No matching price index entry for pricing week"):
    return ApiError("ERR_PRICE_INDEX_MISSING", msg, 409)


def err_boom_mismatch(msg="boom_required delivery assigned to non-boom-capable shift"):
    return ApiError("ERR_BOOM_CAPABILITY_MISMATCH", msg, 409)


def err_drop_limit(msg="Shift booked_drops reached max_drops"):
    return ApiError("ERR_SHIFT_DROP_LIMIT_REACHED", msg, 409)


def err_lien_already_active(msg="Another lien filing on this job is FILED"):
    return ApiError("ERR_LIEN_ALREADY_ACTIVE", msg, 409)


def err_insufficient_inventory(msg="Insufficient qty_available_mbf across lots"):
    return ApiError("ERR_INSUFFICIENT_INVENTORY", msg, 409)


def err_builder_suspended(msg="Builder credit_status is SUSPENDED"):
    return ApiError("ERR_BUILDER_CREDIT_SUSPENDED", msg, 402)


def err_builder_not_active(msg="Builder credit_status is not ACTIVE"):
    return ApiError("ERR_BUILDER_NOT_CREDIT_ACTIVE", msg, 402)


def err_credit_limit(msg="Committed exposure would exceed credit limit"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", msg, 402)


def err_job_cap(msg="Committed exposure would exceed job exposure cap"):
    return ApiError("ERR_JOB_EXPOSURE_CAP_EXCEEDED", msg, 402)


def err_lien_no_exposure(msg="Job has no outstanding settled exposure"):
    return ApiError("ERR_LIEN_NO_OUTSTANDING_EXPOSURE", msg, 402)


def err_order_not_deliverable(msg="Order is not CONFIRMED or already has a live delivery"):
    return ApiError("ERR_ORDER_NOT_DELIVERABLE", msg, 400)
