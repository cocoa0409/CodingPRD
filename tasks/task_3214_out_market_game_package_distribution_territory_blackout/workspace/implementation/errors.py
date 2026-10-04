"""Error classes and error ID constants from the scaffold error catalog."""


class APIError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_STALE_SLATE_VERSION = "ERR_STALE_SLATE_VERSION"
ERR_STALE_SEASON_VERSION = "ERR_STALE_SEASON_VERSION"
ERR_SEASON_CLOSED = "ERR_SEASON_CLOSED"
ERR_OFFER_NOT_AVAILABLE = "ERR_OFFER_NOT_AVAILABLE"
ERR_STUDENT_NOT_VERIFIED = "ERR_STUDENT_NOT_VERIFIED"
ERR_ACCOUNT_KIND_MISMATCH = "ERR_ACCOUNT_KIND_MISMATCH"
ERR_GAME_WEEK_MISMATCH = "ERR_GAME_WEEK_MISMATCH"
ERR_NATIONAL_SELECTION_CONFLICT = "ERR_NATIONAL_SELECTION_CONFLICT"
ERR_SLATE_LOCKED = "ERR_SLATE_LOCKED"
ERR_MARKET_PREFIX_OVERLAP = "ERR_MARKET_PREFIX_OVERLAP"
ERR_SEASON_STRUCTURE = "ERR_SEASON_STRUCTURE"
ERR_OCCUPANCY_CAP_EXCEEDED = "ERR_OCCUPANCY_CAP_EXCEEDED"
ERR_COMPLAINT_WINDOW_EXPIRED = "ERR_COMPLAINT_WINDOW_EXPIRED"
ERR_COMPLAINT_NOT_REFUNDABLE = "ERR_COMPLAINT_NOT_REFUNDABLE"
ERR_REFUND_NOT_AVAILABLE = "ERR_REFUND_NOT_AVAILABLE"
ERR_MULTIVIEW_CAP_REACHED = "ERR_MULTIVIEW_CAP_REACHED"
ERR_FEATURE_NOT_ENTITLED = "ERR_FEATURE_NOT_ENTITLED"
ERR_NOT_OWNER = "ERR_NOT_OWNER"
ERR_DUPLICATE_RESOURCE = "ERR_DUPLICATE_RESOURCE"


def err_unauthenticated(msg="Missing or invalid authentication headers"):
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def err_forbidden_role(msg="Role not permitted for this operation"):
    return APIError(ERR_FORBIDDEN_ROLE, msg, 403)


def err_not_found(msg="Resource not found"):
    return APIError(ERR_NOT_FOUND, msg, 404)


def err_invalid_request(msg="Malformed request payload"):
    return APIError(ERR_INVALID_REQUEST, msg, 400)


def err_invalid_state(msg="Resource not in a valid state for this transition"):
    return APIError(ERR_INVALID_STATE, msg, 409)


def err_already_terminal(msg="Resource is in a terminal state"):
    return APIError(ERR_ALREADY_TERMINAL, msg, 409)


def err_stale_slate_version(msg="Stale slate version"):
    return APIError(ERR_STALE_SLATE_VERSION, msg, 412)


def err_stale_season_version(msg="Stale season version"):
    return APIError(ERR_STALE_SEASON_VERSION, msg, 412)


def err_season_closed(msg="Season is closed to purchases"):
    return APIError(ERR_SEASON_CLOSED, msg, 409)


def err_offer_not_available(msg="Offer is not available for purchase"):
    return APIError(ERR_OFFER_NOT_AVAILABLE, msg, 409)


def err_student_not_verified(msg="Student verification required"):
    return APIError(ERR_STUDENT_NOT_VERIFIED, msg, 422)


def err_account_kind_mismatch(msg="Account kind not permitted for this operation"):
    return APIError(ERR_ACCOUNT_KIND_MISMATCH, msg, 422)


def err_game_week_mismatch(msg="Game does not belong to the slate's week"):
    return APIError(ERR_GAME_WEEK_MISMATCH, msg, 422)


def err_national_selection_conflict(msg="National selection membership conflict"):
    return APIError(ERR_NATIONAL_SELECTION_CONFLICT, msg, 409)


def err_slate_locked(msg="Slate is locked"):
    return APIError(ERR_SLATE_LOCKED, msg, 409)


def err_market_prefix_overlap(msg="ZIP prefix already claimed by another market"):
    return APIError(ERR_MARKET_PREFIX_OVERLAP, msg, 409)


def err_season_structure(msg="Season structure violation"):
    return APIError(ERR_SEASON_STRUCTURE, msg, 422)


def err_occupancy_cap(msg="Occupancy out of bounds"):
    return APIError(ERR_OCCUPANCY_CAP_EXCEEDED, msg, 422)


def err_complaint_window(msg="Complaint grace window expired"):
    return APIError(ERR_COMPLAINT_WINDOW_EXPIRED, msg, 422)


def err_complaint_not_refundable(msg="Complaint category not refundable"):
    return APIError(ERR_COMPLAINT_NOT_REFUNDABLE, msg, 422)


def err_refund_not_available(msg="Refund not available"):
    return APIError(ERR_REFUND_NOT_AVAILABLE, msg, 422)


def err_multiview_cap(msg="Multiview session cap reached"):
    return APIError(ERR_MULTIVIEW_CAP_REACHED, msg, 409)


def err_feature_not_entitled(msg="Feature not entitled on this subscription"):
    return APIError(ERR_FEATURE_NOT_ENTITLED, msg, 403)


def err_not_owner(msg="Acting user does not own this resource"):
    return APIError(ERR_NOT_OWNER, msg, 403)


def err_duplicate(msg="Unique field collision"):
    return APIError(ERR_DUPLICATE_RESOURCE, msg, 409)
