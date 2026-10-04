"""Error class and helpers."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthorized(msg="Missing/invalid X-User-ID/X-User-Role headers or role not permitted"):
    return ApiError("ERR_UNAUTHORIZED", msg, 403)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_invalid_state(msg="Invalid state for this operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_stale_program_version(msg="expected_program_version does not match current program version"):
    return ApiError("ERR_STALE_PROGRAM_VERSION", msg, 412)


def err_stale_market_version(msg="expected_market_version does not match current market version"):
    return ApiError("ERR_STALE_MARKET_VERSION", msg, 412)


def err_program_config_incomplete(msg="Program-type-specific required config fields missing or invalid"):
    return ApiError("ERR_PROGRAM_CONFIG_INCOMPLETE", msg, 400)


def err_program_window_conflict(msg="Program window conflict"):
    return ApiError("ERR_PROGRAM_WINDOW_CONFLICT", msg, 422)


def err_cross_market_reference(msg="Cross-market reference violation"):
    return ApiError("ERR_CROSS_MARKET_REFERENCE", msg, 422)


def err_driver_ineligible(msg="Driver rate_posture is INELIGIBLE"):
    return ApiError("ERR_DRIVER_INELIGIBLE", msg, 422)


def err_fraud_restricted(msg="Driver fraud_posture is RESTRICTED"):
    return ApiError("ERR_FRAUD_RESTRICTED", msg, 422)


def err_budget_exceeded(msg="Operation would drive budget_available_cents negative"):
    return ApiError("ERR_BUDGET_EXCEEDED", msg, 402)


def err_ride_not_completable(msg="Ride not in a source state for this transition"):
    return ApiError("ERR_RIDE_NOT_COMPLETABLE", msg, 409)


def err_ride_already_terminal(msg="Ride is in a terminal state"):
    return ApiError("ERR_RIDE_ALREADY_TERMINAL", msg, 409)


def err_settlement_rides_pending(msg="Week rides still UNDER_REVIEW block finalization"):
    return ApiError("ERR_SETTLEMENT_RIDES_PENDING", msg, 409)


def err_settlement_already_paid(msg="Settlement is PAID"):
    return ApiError("ERR_SETTLEMENT_ALREADY_PAID", msg, 409)


def err_statement_settlements_open(msg="Week settlements still open block publish"):
    return ApiError("ERR_STATEMENT_SETTLEMENTS_OPEN", msg, 409)


def err_appeal_rounds_exhausted(msg="Appeal info rounds exhausted"):
    return ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED", msg, 422)


def err_appeal_not_escalatable(msg="Appeal cannot be escalated yet"):
    return ApiError("ERR_APPEAL_NOT_ESCALATABLE", msg, 422)


def err_appeal_adjustment_required(msg="Non-zero adjustment_cents required"):
    return ApiError("ERR_APPEAL_ADJUSTMENT_REQUIRED", msg, 400)


def err_appeal_identity_mismatch(msg="Acting user is not the appeal's driver"):
    return ApiError("ERR_APPEAL_IDENTITY_MISMATCH", msg, 403)


def err_forecast_not_draft(msg="Forecast is not in DRAFT status"):
    return ApiError("ERR_FORECAST_NOT_DRAFT", msg, 409)


def err_enrollment_duplicate(msg="Driver already has an ACTIVE enrollment on this program"):
    return ApiError("ERR_ENROLLMENT_DUPLICATE", msg, 409)


def err_program_not_guarantee(msg="Program is not a GUARANTEE program"):
    return ApiError("ERR_PROGRAM_NOT_GUARANTEE", msg, 422)


def err_geo_cell_unknown(msg="geo_cell_id is not a member of market.geo_cells"):
    return ApiError("ERR_GEO_CELL_UNKNOWN", msg, 422)
