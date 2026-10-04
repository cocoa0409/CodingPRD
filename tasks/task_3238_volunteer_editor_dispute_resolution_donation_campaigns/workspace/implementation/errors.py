"""Error classes and error ID constants for the Wiki Governance API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# Error catalog (PRD section 5)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                        # 404
ERR_INVALID_STATE = "ERR_INVALID_STATE"                # 409
ERR_COI_UNDISCLOSED = "ERR_COI_UNDISCLOSED"            # 403
ERR_PROTECTION_BLOCKED = "ERR_PROTECTION_BLOCKED"      # 403
ERR_ESCALATION_TOO_SOON = "ERR_ESCALATION_TOO_SOON"    # 409
ERR_GRANT_BUDGET_EXCEEDED = "ERR_GRANT_BUDGET_EXCEEDED"  # 409
ERR_CAMPAIGN_INACTIVE = "ERR_CAMPAIGN_INACTIVE"        # 409
ERR_REFUND_WINDOW_EXPIRED = "ERR_REFUND_WINDOW_EXPIRED"  # 409
ERR_EDITOR_HAS_OPEN_ARBITRATION = "ERR_EDITOR_HAS_OPEN_ARBITRATION"  # 409
ERR_LEGAL_REQUESTS_PENDING = "ERR_LEGAL_REQUESTS_PENDING"  # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"                # 412
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_VANDALISM_SCORE_HIGH = "ERR_VANDALISM_SCORE_HIGH"  # 409
ERR_DISPUTE_ALREADY_OPEN = "ERR_DISPUTE_ALREADY_OPEN"  # 409
ERR_INSUFFICIENT_PRIVILEGE = "ERR_INSUFFICIENT_PRIVILEGE"  # 403
ERR_BANNER_FREQUENCY_CAP = "ERR_BANNER_FREQUENCY_CAP"  # 409
ERR_BANNER_GEO_MISMATCH = "ERR_BANNER_GEO_MISMATCH"    # 409
ERR_GRANT_SCORE_TOO_LOW = "ERR_GRANT_SCORE_TOO_LOW"    # 409
ERR_TAKEDOWN_ARBITRATION_BLOCK = "ERR_TAKEDOWN_ARBITRATION_BLOCK"  # 409


def err_unauthenticated(msg="Missing or invalid X-User-Role header"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def err_unauthorized(msg="Role not permitted for this operation"):
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def err_invalid_state(msg="Resource in wrong state for requested transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def err_invalid_request(msg="Missing required field or malformed payload"):
    return ApiError(ERR_INVALID_REQUEST, msg, 400)


def err_stale_version(msg="expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, msg, 412)
