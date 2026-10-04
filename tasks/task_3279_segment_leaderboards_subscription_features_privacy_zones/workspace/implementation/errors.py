"""Error classes and error id constants (per scaffold §1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for endpoint, or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_validation(msg="Malformed body"):
    return ApiError("ERR_VALIDATION", msg, 422)


def err_invalid_state(msg="Resource in a state that forbids the operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="expected_athlete_version does not match current athlete version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_duplicate_activity(msg="Duplicate activity upload"):
    return ApiError("ERR_DUPLICATE_ACTIVITY", msg, 409)


def err_unique(msg="Uniqueness constraint hit"):
    return ApiError("ERR_UNIQUE_VIOLATION", msg, 409)


def err_safety(msg="Safety rule violated"):
    return ApiError("ERR_SAFETY_VIOLATION", msg, 422)


def err_window(msg="Temporal rule violated"):
    return ApiError("ERR_WINDOW_VIOLATION", msg, 422)


def err_subscription(msg="Feature gated behind an ACTIVE subscription"):
    return ApiError("ERR_SUBSCRIPTION_REQUIRED", msg, 402)


def err_free_tier_cap(msg="Free-tier weekly route-plan cap reached"):
    return ApiError("ERR_FREE_TIER_ROUTE_CAP", msg, 402)


def err_inconsistent(msg="Cross-entity reference inconsistent"):
    return ApiError("ERR_INCONSISTENT_REFERENCE", msg, 422)


def err_flag_self(msg="Reporter is the owner of the effort's activity"):
    return ApiError("ERR_FLAG_SELF", msg, 422)


def err_capacity(msg="Event RSVP would exceed capacity"):
    return ApiError("ERR_CAPACITY_EXCEEDED", msg, 409)


def err_club_archived(msg="Operation targets an ARCHIVED club"):
    return ApiError("ERR_CLUB_ARCHIVED", msg, 409)


def err_segment_overlap(msg="Segment activation would create a duplicate course section"):
    return ApiError("ERR_SEGMENT_OVERLAP", msg, 409)


def err_event_overlap(msg="Event window intersects another PUBLISHED event of the same club"):
    return ApiError("ERR_EVENT_TIME_OVERLAP", msg, 409)


def err_dup_membership(msg="Athlete already holds a PENDING or ACTIVE membership in this club"):
    return ApiError("ERR_DUPLICATE_MEMBERSHIP", msg, 409)


def err_already_joined(msg="Athlete already holds a JOINED or COMPLETED participation in this challenge"):
    return ApiError("ERR_ALREADY_JOINED", msg, 409)
