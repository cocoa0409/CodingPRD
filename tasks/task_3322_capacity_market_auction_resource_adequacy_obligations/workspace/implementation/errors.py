"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted for this endpoint."):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Missing required field, enum violation, or numeric range violation."):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Requested transition does not exist from the resource's current state."):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_version(msg="OCC mismatch: expected version does not equal the parent's current version."):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_ownership(msg="Acting ResourceOwner does not own the resource being mutated."):
    return ApiError("ERR_OWNERSHIP_VIOLATION", msg, 403)


def err_owner_suspended(msg="SUSPENDED owner attempted to submit an offer, replacement, or measurement report."):
    return ApiError("ERR_OWNER_SUSPENDED", msg, 422)


def err_event_overlap(msg="EmergencyEvent PAI overlaps an existing non-terminal event's interval."):
    return ApiError("ERR_EVENT_OVERLAP", msg, 409)


def err_measurement_overlap(msg="A VERIFIED MeasurementReport for the same resource already covers an overlapping window."):
    return ApiError("ERR_MEASUREMENT_WINDOW_OVERLAP", msg, 409)


def err_invalid_time_range(msg="End <= start, or event window outside the delivery year's planning period."):
    return ApiError("ERR_INVALID_TIME_RANGE", msg, 422)


def err_forecast_shares(msg="zonal_peak_shares missing a top-level zone or fractions do not sum to exactly 1.000."):
    return ApiError("ERR_FORECAST_SHARES_INVALID", msg, 422)


def err_offer_exceeds_ucap(msg="offer_mw exceeds the resource's accredited UCAP minus MW already offered into the same run."):
    return ApiError("ERR_OFFER_EXCEEDS_UCAP", msg, 422)


def err_replacement_not_deliverable(msg="Replacement resource lacks headroom, is the same resource, or is not deliverable."):
    return ApiError("ERR_REPLACEMENT_NOT_DELIVERABLE", msg, 422)


def err_mitigation_pending(msg="Clear attempted while a MitigationReview is still PENDING."):
    return ApiError("ERR_MITIGATION_PENDING", msg, 409)


def err_accreditation_conflict(msg="An EFFECTIVE accreditation already exists for (resource_id, delivery_year_id)."):
    return ApiError("ERR_ACCREDITATION_CONFLICT", msg, 409)


def err_replacement_exceeds(msg="replacement_mw <= 0 or greater than the commitment's current committed_mw."):
    return ApiError("ERR_REPLACEMENT_EXCEEDS_COMMITMENT", msg, 422)


def err_default_threshold(msg="Commitment default requires cumulative_performance_score < 0.40 and >= 2 FINALIZED assessments."):
    return ApiError("ERR_DEFAULT_THRESHOLD_NOT_MET", msg, 422)


def err_measurement_not_applicable(msg="MeasurementReport submitted for a GEN resource."):
    return ApiError("ERR_MEASUREMENT_NOT_APPLICABLE", msg, 422)
