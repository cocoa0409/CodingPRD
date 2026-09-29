"""Error catalogue (PRD 5) and the ApiError exception carried through the ladder."""

ERROR_STATUS = {
    # Rungs 1-5: credentials, role, vendor identity, vendor scope
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_VENDOR_IDENTITY_UNKNOWN": 403,
    "ERR_VENDOR_SCOPE_VIOLATION": 403,
    # Rung 6: payload schema
    "ERR_INVALID_REQUEST": 400,
    # Rungs 7-8: path and reference existence
    "ERR_TITLE_NOT_FOUND": 404,
    "ERR_ASSET_NOT_FOUND": 404,
    "ERR_LADDER_NOT_FOUND": 404,
    "ERR_PACKAGE_NOT_FOUND": 404,
    "ERR_DEVICE_PROFILE_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_RESERVATION_NOT_FOUND": 404,
    "ERR_WINDOW_NOT_FOUND": 404,
    "ERR_JOB_NOT_FOUND": 404,
    "ERR_METRIC_WINDOW_NOT_FOUND": 404,
    # Rung 9: natural-key uniqueness
    "ERR_DUPLICATE_EXTERNAL_REF": 409,
    "ERR_DUPLICATE_VENDOR_CODE": 409,
    "ERR_DUPLICATE_DEVICE_CLASS": 409,
    # Rung 10: own-entity state
    "ERR_ASSET_STATE_INVALID": 409,
    "ERR_LADDER_STATE_INVALID": 409,
    "ERR_PACKAGE_STATE_INVALID": 409,
    "ERR_RESERVATION_STATE_INVALID": 409,
    "ERR_JOB_STATE_INVALID": 409,
    "ERR_WINDOW_STATE_INVALID": 409,
    # Rung 11: cross-entity state
    "ERR_NO_PASSED_ASSET": 409,
    "ERR_ASSET_REMEDIATION_PENDING": 409,
    "ERR_PACKAGE_NOT_READY": 409,
    "ERR_LADDER_NOT_LOCKED": 409,
    "ERR_LADDER_NOT_BINDABLE": 409,
    "ERR_TITLE_LEGALLY_BLOCKED": 409,
    "ERR_NO_PACKAGED_DRM": 409,
    # Rung 12: optimistic concurrency
    "ERR_STALE_TITLE_VERSION": 412,
    # Entitlement decision denials
    "ERR_ENTITLEMENT_NO_RULE": 403,
    "ERR_CONCURRENCY_LIMIT_EXCEEDED": 403,
    "ERR_OFFLINE_PLAYBACK_DENIED": 403,
    # Rung 13: content-protection floor
    "ERR_HDCP_FLOOR_VIOLATION": 422,
    "ERR_OFFLINE_NOT_LICENSED": 422,
    "ERR_DRM_SYSTEM_UNSUPPORTED": 422,
    # Rung 14: cross-aggregate coherence
    "ERR_LADDER_TITLE_MISMATCH": 422,
    "ERR_VENDOR_REGION_NOT_SERVED": 422,
    "ERR_NOT_LIVE_EVENT_TITLE": 422,
    "ERR_FAILOVER_SAME_AS_PRIMARY": 422,
    "ERR_REPROCESS_CODEC_UNCHANGED": 422,
    "ERR_RULE_REGION_NOT_LICENSED": 422,
    # Rung 15: interval well-formedness and placement
    "ERR_WINDOW_BOUNDS_INVALID": 422,
    "ERR_WINDOW_IN_PAST": 422,
    "ERR_METRIC_WINDOW_IN_FUTURE": 422,
    "ERR_RESERVATION_OUTSIDE_LICENSE": 422,
    # Rung 16: interval conflict
    "ERR_WINDOW_OVERLAP": 409,
    # Rung 17: shape and cardinality
    "ERR_RUNG_SHAPE_INVALID": 409,
    "ERR_DUPLICATE_ENTITLEMENT_RULE": 409,
    "ERR_REPROCESS_JOB_IN_FLIGHT": 409,
    "ERR_DUPLICATE_ROUTING_POLICY": 409,
    # Rungs 18-20: selector pool, capacity, budget
    "ERR_NO_ELIGIBLE_VENDOR": 422,
    "ERR_REPROCESS_NO_SOURCE_ASSET": 422,
    "ERR_VENDOR_CAPACITY_EXCEEDED": 422,
    "ERR_ENCODE_BUDGET_EXCEEDED": 422,
}


class ApiError(Exception):
    """A single failure, reported with exactly one error identifier."""

    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower()
