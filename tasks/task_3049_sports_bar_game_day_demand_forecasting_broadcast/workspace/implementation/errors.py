"""Error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted for this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Referenced resource does not exist or is out of scope"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Malformed payload, missing required field, or invalid enum"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg="Resource not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 400, msg)


def stale_version(msg="expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def event_window_conflict(msg="Event window is invalid or conflicts"):
    return ApiError("ERR_EVENT_WINDOW_CONFLICT", 400, msg)


def screen_already_assigned(msg="screen_id already has an ACTIVE assignment in this zone"):
    return ApiError("ERR_SCREEN_ALREADY_ASSIGNED", 409, msg)


def blackout_window_active(msg="Assignment would violate an active blackout window"):
    return ApiError("ERR_BLACKOUT_WINDOW_ACTIVE", 400, msg)


def license_not_active(msg="License for the league is not ACTIVE"):
    return ApiError("ERR_LICENSE_NOT_ACTIVE", 400, msg)


def waitlist_full(msg="All zones are FULL; waitlist join rejected"):
    return ApiError("ERR_WAITLIST_FULL", 400, msg)


def table_hold_expired(msg="Called party did not check in within the hold window"):
    return ApiError("ERR_TABLE_HOLD_EXPIRED", 400, msg)


def too_many_no_shows(msg="Guest has 3 or more unredeemed no-shows"):
    return ApiError("ERR_TOO_MANY_NO_SHOWS", 400, msg)


def ppv_requires_event(msg="PPV check must reference an Event with kind=PPV"):
    return ApiError("ERR_PPV_REQUIRES_EVENT", 400, msg)


def contest_not_open(msg="Fantasy contest is not OPEN for registration"):
    return ApiError("ERR_CONTEST_NOT_OPEN", 400, msg)


def promo_window_invalid(msg="Promo end_date before start_date or overlapping rule"):
    return ApiError("ERR_PROMO_WINDOW_INVALID", 400, msg)


def shift_window_invalid(msg="Shift end_time must be after start_time"):
    return ApiError("ERR_SHIFT_WINDOW_INVALID", 400, msg)


def quantity_invalid(msg="Pieces or portion_count must be a positive integer"):
    return ApiError("ERR_QUANTITY_INVALID", 400, msg)


def prize_structure_invalid(msg="prize_structure shares must sum to 1.0 within 0.001"):
    return ApiError("ERR_PRIZE_STRUCTURE_INVALID", 400, msg)


def capacity_exceeded(msg="Operation would exceed venue or zone capacity"):
    return ApiError("ERR_CAPACITY_EXCEEDED", 400, msg)


def guest_not_found(msg="Referenced guest does not exist"):
    return ApiError("ERR_GUEST_NOT_FOUND", 404, msg)


def event_not_found(msg="Referenced event does not exist"):
    return ApiError("ERR_EVENT_NOT_FOUND", 404, msg)
