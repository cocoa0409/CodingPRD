"""API error type and the full error catalog (SCAFFOLD §1.6 / PRD §5)."""


class ApiError(Exception):
    """Exception carrying the machine-readable error_id and HTTP status."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error identifiers (each maps to a fixed HTTP status per the catalog).
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                            # 403
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                # 400
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"                    # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_CASE_NOT_FORFEITED = "ERR_CASE_NOT_FORFEITED"          # 409
ERR_APPEAL_EXHAUSTED = "ERR_APPEAL_EXHAUSTED"              # 409
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"                    # 403
ERR_DUPLICATE_CASE_NUMBER = "ERR_DUPLICATE_CASE_NUMBER"    # 409
ERR_PRIORITY_POSITION_CONFLICT = "ERR_PRIORITY_POSITION_CONFLICT"  # 409
ERR_CUSTODY_WINDOW_BREAK = "ERR_CUSTODY_WINDOW_BREAK"      # 409
ERR_AUCTION_SLOT_CONFLICT = "ERR_AUCTION_SLOT_CONFLICT"    # 409
ERR_SALE_ALREADY_ACTIVE = "ERR_SALE_ALREADY_ACTIVE"        # 409
ERR_OUTCOME_KIND_MISMATCH = "ERR_OUTCOME_KIND_MISMATCH"    # 422
ERR_RATIO_BELOW_THRESHOLD = "ERR_RATIO_BELOW_THRESHOLD"    # 422
ERR_RESERVE_ABOVE_VALUE = "ERR_RESERVE_ABOVE_VALUE"        # 422
ERR_SHARE_BELOW_MINIMUM = "ERR_SHARE_BELOW_MINIMUM"        # 422
ERR_INSUFFICIENT_PROCEEDS = "ERR_INSUFFICIENT_PROCEEDS"    # 422
ERR_NEGATIVE_HOLDING_COST = "ERR_NEGATIVE_HOLDING_COST"    # 422
ERR_RETENTION_VALUE_TOO_LOW = "ERR_RETENTION_VALUE_TOO_LOW"  # 422
ERR_RETENTION_BLOCKED_HOLDING_COST = "ERR_RETENTION_BLOCKED_HOLDING_COST"  # 422
ERR_DEPRECIATION_EXCEEDS_VALUE = "ERR_DEPRECIATION_EXCEEDS_VALUE"  # 422
ERR_SLOT_IN_PAST = "ERR_SLOT_IN_PAST"                      # 409
ERR_DISPUTE_WINDOW_EXPIRED = "ERR_DISPUTE_WINDOW_EXPIRED"  # 409


def unauthenticated(message="Missing X-User-Role/X-User-ID or unrecognized role"):
    return ApiError(ERR_UNAUTHENTICATED, 401, message)


def forbidden(message="Role not permitted on this endpoint, or identity check failed"):
    return ApiError(ERR_FORBIDDEN, 403, message)


def invalid_request(message):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def not_found(message="Path id or body foreign-key id does not resolve"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def stale_version(message="expected_asset_version does not match the Asset's current version"):
    return ApiError(ERR_STALE_VERSION, 412, message)


def invalid_state(message="Entity is not in a valid from-state for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, message)


def case_not_forfeited(message="Operation requires SeizureCase.status == FORFEITED"):
    return ApiError(ERR_CASE_NOT_FORFEITED, 409, message)


def appeal_exhausted(message="Appeal limit reached for this third-party interest"):
    return ApiError(ERR_APPEAL_EXHAUSTED, 409, message)


def sod_violation(message="Segregation of duties: approver/adjudicator must differ from creator/requester"):
    return ApiError(ERR_SOD_VIOLATION, 403, message)
