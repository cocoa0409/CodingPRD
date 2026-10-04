"""Error classes and error ID constants for the chart ranking API."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_CHART_FROZEN = "ERR_CHART_FROZEN"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ACCOUNT_SUSPENDED = "ERR_ACCOUNT_SUSPENDED"
ERR_WEEK_NOT_CLOSED = "ERR_WEEK_NOT_CLOSED"
ERR_NO_ACTIVE_METHODOLOGY = "ERR_NO_ACTIVE_METHODOLOGY"
ERR_REPORTING_CUTOFF_PASSED = "ERR_REPORTING_CUTOFF_PASSED"
ERR_WEEK_WINDOW_OVERLAP = "ERR_WEEK_WINDOW_OVERLAP"
ERR_AVAILABILITY_WINDOW = "ERR_AVAILABILITY_WINDOW"
ERR_COMPONENT_KIND_MISMATCH = "ERR_COMPONENT_KIND_MISMATCH"
ERR_DUPLICATE_REPORT_BATCH = "ERR_DUPLICATE_REPORT_BATCH"
ERR_GENRE_MISMATCH = "ERR_GENRE_MISMATCH"
ERR_DISPUTE_INVALID = "ERR_DISPUTE_INVALID"
ERR_RECLASSIFICATION_TARGET_MISMATCH = "ERR_RECLASSIFICATION_TARGET_MISMATCH"
ERR_SIGNAL_ALREADY_ESCALATED = "ERR_SIGNAL_ALREADY_ESCALATED"
ERR_DUTY_SEGREGATION_VIOLATION = "ERR_DUTY_SEGREGATION_VIOLATION"
ERR_TITLE_DISQUALIFIED = "ERR_TITLE_DISQUALIFIED"
ERR_PRICE_BELOW_FLOOR = "ERR_PRICE_BELOW_FLOOR"
ERR_RELEASE_WINDOW_VIOLATION = "ERR_RELEASE_WINDOW_VIOLATION"
ERR_BUNDLE_CHANNEL_INVALID = "ERR_BUNDLE_CHANNEL_INVALID"
ERR_HOLIDAY_WINDOW_INVALID = "ERR_HOLIDAY_WINDOW_INVALID"


def unauthenticated(msg="Missing or malformed authentication headers"):
    return ApiError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg="Role not permitted on this endpoint"):
    return ApiError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg="Resource not found"):
    return ApiError(ERR_NOT_FOUND, msg, 404)


def stale_version(msg="Chart version has advanced since last observation"):
    return ApiError(ERR_STALE_VERSION, msg, 412)


def chart_frozen(msg="Operation blocked while a chart freeze is ACTIVE"):
    return ApiError(ERR_CHART_FROZEN, msg, 409)


def invalid_state(msg="Entity is not in a state permitting this transition"):
    return ApiError(ERR_INVALID_STATE, msg, 409)


def account_suspended(msg="Account or provider is suspended"):
    return ApiError(ERR_ACCOUNT_SUSPENDED, msg, 409)


def week_not_closed(msg="Week lock attempted before closes_at"):
    return ApiError(ERR_WEEK_NOT_CLOSED, msg, 409)


def no_active_methodology(msg="No ACTIVE methodology version applies to this week"):
    return ApiError(ERR_NO_ACTIVE_METHODOLOGY, msg, 409)


def reporting_cutoff_passed(msg="event_time outside [opens_at, reporting_cutoff)"):
    return ApiError(ERR_REPORTING_CUTOFF_PASSED, msg, 422)


def week_window_overlap(msg="New week window strictly overlaps an existing week"):
    return ApiError(ERR_WEEK_WINDOW_OVERLAP, msg, 409)


def availability_window(msg="Title outside its availability window"):
    return ApiError(ERR_AVAILABILITY_WINDOW, msg, 422)


def component_kind_mismatch(msg="component_kind not permitted by provider feed_kind"):
    return ApiError(ERR_COMPONENT_KIND_MISMATCH, msg, 422)


def duplicate_report_batch(msg="Duplicate file_fingerprint from this provider"):
    return ApiError(ERR_DUPLICATE_REPORT_BATCH, msg, 409)


def genre_mismatch(msg="Title genre or product kind does not match chart admission"):
    return ApiError(ERR_GENRE_MISMATCH, msg, 422)


def dispute_invalid(msg="Dispute invalid: MAIN chart or claimed_genre equals current"):
    return ApiError(ERR_DISPUTE_INVALID, msg, 422)


def reclassification_target_mismatch(msg="new_genre_tag must equal dispute chart genre_tag"):
    return ApiError(ERR_RECLASSIFICATION_TARGET_MISMATCH, msg, 422)


def signal_already_escalated(msg="Signal already has an investigation"):
    return ApiError(ERR_SIGNAL_ALREADY_ESCALATED, msg, 409)


def duty_segregation_violation(msg="Segregation of duties violated"):
    return ApiError(ERR_DUTY_SEGREGATION_VIOLATION, msg, 403)


def title_disqualified(msg="Title eligibility_posture is DISQUALIFIED"):
    return ApiError(ERR_TITLE_DISQUALIFIED, msg, 409)


def price_below_floor(msg="Title base_price_cents below price floor"):
    return ApiError(ERR_PRICE_BELOW_FLOOR, msg, 422)


def release_window_violation(msg="Week opens before title release_date"):
    return ApiError(ERR_RELEASE_WINDOW_VIOLATION, msg, 422)


def bundle_channel_invalid(msg="Sale batch against a non-ALBUM title"):
    return ApiError(ERR_BUNDLE_CHANNEL_INVALID, msg, 422)


def holiday_window_invalid(msg="Holiday adjustment window invalid"):
    return ApiError(ERR_HOLIDAY_WINDOW_INVALID, msg, 422)
