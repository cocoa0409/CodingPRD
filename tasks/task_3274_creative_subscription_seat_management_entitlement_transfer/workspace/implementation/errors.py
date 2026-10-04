"""Error types and helpers."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN_ROLE", 403, msg)


def err_identity_mismatch(msg="Identity does not resolve in scope"):
    return ApiError("ERR_IDENTITY_MISMATCH", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_reference_not_found(msg="Referenced resource not found"):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_invalid_state(msg="Invalid state for requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_org_frozen(msg="Organization is frozen"):
    return ApiError("ERR_ORG_FROZEN", 409, msg)


def err_audit_freeze(msg="Asset purge blocked under audit"):
    return ApiError("ERR_AUDIT_FREEZE", 409, msg)


def err_segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_offline_activation(msg="Offline activation not allowed"):
    return ApiError("ERR_OFFLINE_ACTIVATION_NOT_ALLOWED", 422, msg)


def err_deployment_mode(msg="Deployment mode not permitted"):
    return ApiError("ERR_DEPLOYMENT_MODE_NOT_PERMITTED", 422, msg)


def err_duplicate_plan_seat(msg="User already holds an assigned seat under this plan"):
    return ApiError("ERR_DUPLICATE_PLAN_SEAT", 409, msg)


def err_device_limit(msg="Device activation limit exceeded"):
    return ApiError("ERR_DEVICE_LIMIT_EXCEEDED", 422, msg)


def err_cross_org(msg="Cross-organization reference"):
    return ApiError("ERR_CROSS_ORG_REFERENCE", 422, msg)


def err_reclaim_grace(msg="Reclaim grace period still active"):
    return ApiError("ERR_RECLAIM_GRACE_ACTIVE", 409, msg)


def err_transfer_expired(msg="Transfer request expired"):
    return ApiError("ERR_TRANSFER_EXPIRED", 409, msg)


def err_deadline_not_future(msg="Deadline must be strictly in the future"):
    return ApiError("ERR_DEADLINE_NOT_FUTURE", 422, msg)


def err_no_available_version(msg="No available product version for plan"):
    return ApiError("ERR_NO_AVAILABLE_VERSION", 409, msg)


def err_seat_capacity(msg="Seat capacity exceeded"):
    return ApiError("ERR_SEAT_CAPACITY_EXCEEDED", 422, msg)


def err_monthly_no_etf(msg="Monthly plans have no ETF path"):
    return ApiError("ERR_MONTHLY_NO_ETF", 422, msg)


def err_no_reseller(msg="No active reseller in region"):
    return ApiError("ERR_NO_RESELLER_AVAILABLE", 422, msg)


def err_reseller_suspended(msg="Reseller is not active"):
    return ApiError("ERR_RESELLER_SUSPENDED", 409, msg)


def err_subscription_not_active(msg="Subscription is not ACTIVE"):
    return ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409, msg)


def err_user_not_active(msg="End user is not ACTIVE"):
    return ApiError("ERR_USER_NOT_ACTIVE", 409, msg)
