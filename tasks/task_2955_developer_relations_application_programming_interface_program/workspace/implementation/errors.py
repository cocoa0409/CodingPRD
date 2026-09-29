"""Complete error catalogue (65 identifiers) and the ApiError exception."""

ERROR_STATUS = {
    # --- band 1: authentication / authorisation
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNKNOWN_DEVELOPER_IDENTITY": 401,
    "ERR_UNAUTHORIZED": 403,
    # --- band 2: request shape
    "ERR_INVALID_REQUEST": 400,
    # --- band 3: existence
    "ERR_DEVELOPER_NOT_FOUND": 404,
    "ERR_API_PRODUCT_NOT_FOUND": 404,
    "ERR_API_VERSION_NOT_FOUND": 404,
    "ERR_ACCESS_APPLICATION_NOT_FOUND": 404,
    "ERR_QUOTA_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_UPGRADE_REQUEST_NOT_FOUND": 404,
    "ERR_USAGE_WINDOW_NOT_FOUND": 404,
    "ERR_SANDBOX_LEASE_NOT_FOUND": 404,
    "ERR_VIOLATION_CASE_NOT_FOUND": 404,
    "ERR_SUPPORT_CASE_NOT_FOUND": 404,
    "ERR_FEEDBACK_ITEM_NOT_FOUND": 404,
    # --- band 4: ownership
    "ERR_NOT_RESOURCE_OWNER": 403,
    # --- band 5: optimistic concurrency
    "ERR_STALE_PRODUCT_VERSION": 412,
    "ERR_STALE_ASSIGNMENT_VERSION": 412,
    # --- band 6: state
    "ERR_APPLICATION_STATE_INVALID": 409,
    "ERR_ASSIGNMENT_NOT_ACTIVE": 409,
    "ERR_ASSIGNMENT_STATE_INVALID": 409,
    "ERR_VERSION_STATE_INVALID": 409,
    "ERR_CASE_STATE_INVALID": 409,
    "ERR_SUPPORT_CASE_STATE_INVALID": 409,
    "ERR_LEASE_NOT_ACTIVE": 409,
    "ERR_FEEDBACK_STATE_INVALID": 409,
    "ERR_NO_PENDING_UPGRADE_REQUESTS": 409,
    # --- band 7: eligibility / safety
    "ERR_DEVELOPER_STANDING_BLOCKED": 422,
    "ERR_DEVELOPER_REVOKED": 422,
    "ERR_TOS_VERSION_STALE": 422,
    "ERR_DOCS_NOT_ACKNOWLEDGED": 422,
    "ERR_SCOPE_SENSITIVITY_NOT_PERMITTED": 422,
    "ERR_JUSTIFICATION_INSUFFICIENT": 422,
    "ERR_SEVERITY_NOT_ENTITLED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    # --- band 8: temporal, fiscal and workflow-specific
    "ERR_CLOCK_REWIND": 422,
    "ERR_WINDOW_NOT_ALIGNED": 422,
    "ERR_WINDOW_IN_FUTURE": 422,
    "ERR_WINDOW_OUT_OF_ORDER": 422,
    "ERR_WINDOW_DUPLICATE": 409,
    "ERR_NOTICE_PERIOD_TOO_SHORT": 422,
    "ERR_DEPRECATION_WINDOW_FULL": 422,
    "ERR_SANDBOX_INTERVAL_OVERLAP": 409,
    "ERR_INCIDENT_COALESCE_WINDOW": 409,
    "ERR_COMMUNICATION_OUT_OF_ORDER": 422,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_CERTIFICATION_EXPIRED": 422,
    "ERR_VERSION_NOT_GRANTABLE": 422,
    "ERR_MIGRATION_GUIDE_MISSING": 422,
    "ERR_EVIDENCE_NOT_ATTRIBUTABLE": 422,
    "ERR_SUPPORT_CASE_KIND_MISMATCH": 422,
    "ERR_ESCALATION_NOT_ENTITLED": 422,
    "ERR_DIRECTORY_PREREQUISITES_UNMET": 422,
    "ERR_DUPLICATE_APPLICATION": 409,
    "ERR_ASSIGNMENT_ALREADY_EXISTS": 409,
    "ERR_REVISION_LIMIT_REACHED": 422,
    "ERR_TIER_ESCALATION_NOT_PERMITTED": 422,
    "ERR_UPGRADE_NOT_AN_INCREASE": 422,
    "ERR_NO_COMMUNICATION_RECORDED": 422,
    "ERR_APPEAL_ALREADY_FILED": 409,
    "ERR_TIER_CEILING_REACHED": 422,
    "ERR_SUSTAINED_POOL_EXHAUSTED": 422,
    "ERR_MONTHLY_POOL_EXHAUSTED": 422,
    "ERR_POOL_BELOW_ALLOCATED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role are both required and must be non-empty.",
    "ERR_UNKNOWN_ROLE": "X-User-Role is not one of the declared roles.",
    "ERR_UNKNOWN_DEVELOPER_IDENTITY": "X-User-ID does not identify a registered developer.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request payload is malformed or violates a field constraint.",
    "ERR_NOT_RESOURCE_OWNER": "A developer may only act on resources it owns.",
}


class ApiError(Exception):
    """Raised anywhere in the request pipeline to abort with a catalogue error."""

    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id) or error_id
        super().__init__(self.message)


def invalid(message="The request payload is malformed or violates a field constraint."):
    raise ApiError("ERR_INVALID_REQUEST", message)
