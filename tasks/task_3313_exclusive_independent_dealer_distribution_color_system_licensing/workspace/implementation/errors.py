"""Error catalog and exception type."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="missing or invalid authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_unauthorized(msg="role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_not_found(msg="referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="malformed payload"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="requested transition does not exist from current state"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_dealer_not_active(msg="dealer status does not permit this operation"):
    return ApiError("ERR_DEALER_NOT_ACTIVE", msg, 409)


def err_license_not_active(msg="no ACTIVE license covering this colorant system"):
    return ApiError("ERR_LICENSE_NOT_ACTIVE", msg, 409)


def err_duplicate(msg="uniqueness violation"):
    return ApiError("ERR_DUPLICATE", msg, 409)


def err_equipment_not_calibrated(msg="no CALIBRATED equipment unit for the line's colorant system"):
    return ApiError("ERR_EQUIPMENT_NOT_CALIBRATED", msg, 422)


def err_rematch_required(msg="formula has a PENDING rematch task at this dealer"):
    return ApiError("ERR_REMATCH_REQUIRED", msg, 422)


def err_channel_exclusivity(msg="BIGBOX channel event rejected while posture is BLOCKED"):
    return ApiError("ERR_CHANNEL_EXCLUSIVITY_VIOLATION", msg, 422)


def err_channel_event_overlap(msg="channel event exactly duplicates an existing CONFIRMED period"):
    return ApiError("ERR_CHANNEL_EVENT_OVERLAP", msg, 422)


def err_attestation_stale(msg="exclusivity attestation older than 366 days"):
    return ApiError("ERR_ATTESTATION_STALE", msg, 422)


def err_claim_window(msg="co-op claim activity_date out of window"):
    return ApiError("ERR_CLAIM_WINDOW_EXPIRED", msg, 422)


def err_effective_date_invalid(msg="formulation change effective_date invalid for this transition"):
    return ApiError("ERR_EFFECTIVE_DATE_INVALID", msg, 422)


def err_invalid_period(msg="period_end must be after period_start; period_start not in the future"):
    return ApiError("ERR_INVALID_PERIOD", msg, 422)


def err_reference_inactive(msg="referenced configuration is inactive"):
    return ApiError("ERR_REFERENCE_INACTIVE", msg, 422)


def err_territory_conflict(msg="territory-conflict approval requires ChannelDirector after neighbor notification"):
    return ApiError("ERR_TERRITORY_CONFLICT", msg, 422)


def err_min_inventory(msg="INITIAL_STOCK order below the colorant system's minimum units"):
    return ApiError("ERR_MIN_INVENTORY_UNMET", msg, 422)


def err_coop_funds(msg="co-op claim exceeds available balance or dealer not branding compliant"):
    return ApiError("ERR_COOP_FUNDS_INSUFFICIENT", msg, 422)
