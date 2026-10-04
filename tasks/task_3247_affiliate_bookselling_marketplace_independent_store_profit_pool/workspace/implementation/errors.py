"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or unknown X-User-Role"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role lacks permission for this endpoint or action"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_forbidden_owner(msg="Ownership mismatch"):
    return ApiError("ERR_FORBIDDEN_OWNER_MISMATCH", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_reference_not_found(msg="Body foreign key does not resolve"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def err_validation(msg="Malformed request body"):
    return ApiError("ERR_VALIDATION", 400, msg)


def err_invalid_state(msg="Transition precondition not met"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="expected_distribution_version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_affiliate_not_active(msg="Attributed affiliate not ACTIVE"):
    return ApiError("ERR_AFFILIATE_NOT_ACTIVE", 422, msg)


def err_book_unavailable(msg="Book DELISTED or publisher SUSPENDED"):
    return ApiError("ERR_BOOK_UNAVAILABLE", 422, msg)


def err_attribution_ambiguous(msg="Both or neither of store/partner attribution set"):
    return ApiError("ERR_ATTRIBUTION_AMBIGUOUS", 422, msg)


def err_list_attribution(msg="source_list attribution mismatch"):
    return ApiError("ERR_LIST_ATTRIBUTION_MISMATCH", 422, msg)


def err_promotion_window_conflict(msg="Promotion window conflict"):
    return ApiError("ERR_PROMOTION_WINDOW_CONFLICT", 409, msg)


def err_pool_period_overlap(msg="Pool period overlaps an existing distribution"):
    return ApiError("ERR_POOL_PERIOD_OVERLAP", 409, msg)


def err_return_window_closed(msg="Return window closed or invalid reason for format"):
    return ApiError("ERR_RETURN_WINDOW_CLOSED", 422, msg)


def err_window_not_satisfied(msg="Temporal window not satisfied"):
    return ApiError("ERR_WINDOW_NOT_SATISFIED", 422, msg)


def err_commercial_terms(msg="Commercial terms invalid"):
    return ApiError("ERR_COMMERCIAL_TERMS_INVALID", 422, msg)


def err_pool_sum_mismatch(msg="Share lines do not sum to pool_cents"):
    return ApiError("ERR_POOL_SUM_MISMATCH", 422, msg)


def err_list_not_publishable(msg="List is empty"):
    return ApiError("ERR_LIST_NOT_PUBLISHABLE", 422, msg)


def err_return_quantity(msg="Return quantity exceeds unreturned balance"):
    return ApiError("ERR_RETURN_QUANTITY_EXCEEDED", 422, msg)


def err_store_settlement(msg="Deactivate with non-zero balance or an open payout"):
    return ApiError("ERR_STORE_SETTLEMENT_OUTSTANDING", 422, msg)
