"""Error catalogue and the ApiError exception carried through the request."""

ERROR_HTTP_STATUS = {
    # --- auth ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INSPECTOR_NOT_CERTIFIED": 403,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    # --- existence ---
    "ERR_WATER_BODY_NOT_FOUND": 404,
    "ERR_STATION_NOT_FOUND": 404,
    "ERR_INSPECTOR_NOT_FOUND": 404,
    "ERR_WATERCRAFT_NOT_FOUND": 404,
    "ERR_INSPECTION_RECORD_NOT_FOUND": 404,
    "ERR_RECIPROCITY_AGREEMENT_NOT_FOUND": 404,
    "ERR_DECON_ORDER_NOT_FOUND": 404,
    "ERR_QUARANTINE_ORDER_NOT_FOUND": 404,
    "ERR_DETECTION_REPORT_NOT_FOUND": 404,
    "ERR_CAMPAIGN_NOT_FOUND": 404,
    # --- uniqueness ---
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_SEAL_NUMBER_DUPLICATE": 409,
    # --- state ---
    "ERR_INVALID_STATION_STATE": 409,
    "ERR_STATION_NOT_OPEN": 409,
    "ERR_INVALID_INSPECTOR_STATE": 409,
    "ERR_RECORD_NOT_SCREENED": 409,
    "ERR_RECORD_ALREADY_DISPOSED": 409,
    "ERR_RECORD_NOT_AWAITING_DECON": 409,
    "ERR_INVALID_ENFORCEMENT_STATE": 409,
    "ERR_DECON_NOT_TREATED": 409,
    "ERR_DECON_ALREADY_TERMINAL": 409,
    "ERR_QUARANTINE_NOT_SEALED": 409,
    "ERR_QUARANTINE_RELEASE_NOT_REQUESTED": 409,
    "ERR_REPORT_INVALID_STATE": 409,
    "ERR_INVALID_CAMPAIGN_STATE": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_WATERCRAFT_VERSION": 412,
    "ERR_STALE_INSPECTION_RECORD_VERSION": 412,
    # --- business safety ---
    "ERR_INSPECTOR_NOT_ACTIVE": 409,
    "ERR_STATION_NOT_HOT_WATER_CAPABLE": 409,
    "ERR_TREATMENT_BELOW_MINIMUM": 422,
    "ERR_DRY_TIME_NOT_ELAPSED": 409,
    "ERR_HOLD_PERIOD_NOT_ELAPSED": 409,
    "ERR_DECON_REQUIRED_BEFORE_RELEASE": 409,
    "ERR_DECON_REQUIRED_BEFORE_PASS": 409,
    "ERR_DECON_ATTEMPTS_EXHAUSTED": 409,
    "ERR_HOURS_WINDOW_OVERLAP": 409,
    "ERR_WATERCRAFT_ALREADY_QUARANTINED": 409,
    "ERR_DECON_BAY_UNAVAILABLE": 409,
    "ERR_QUARANTINE_NOT_WARRANTED": 409,
    "ERR_STATION_SEAL_STOCK_EXHAUSTED": 409,
    "ERR_STATION_OUTSIDE_OPERATING_HOURS": 409,
    "ERR_EVALUATION_WINDOW_NOT_ENDED": 409,
    "ERR_STATION_SITING_INVALID": 422,
    "ERR_WATER_BODY_CYCLE": 422,
    "ERR_SEAL_PREFIX_MISMATCH": 422,
    "ERR_SEAL_RECIPROCITY_EXPIRED": 422,
    "ERR_PRIOR_WATER_BODY_MISMATCH": 422,
    "ERR_NO_STATIONS_FOR_CAMPAIGN": 422,
    "ERR_NO_INSPECTIONS_IN_WINDOW": 422,
    "ERR_CAMPAIGN_BUDGET_EXCEEDED": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unknown role.",
    "ERR_UNAUTHORIZED": "The acting role is not permitted on this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the targeted resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids the acting principal from this action.",
    "ERR_INSPECTOR_NOT_CERTIFIED": "The acting inspector does not hold the required certification.",
    "ERR_INVALID_REQUEST": "The request body is not structurally valid.",
    "ERR_INVALID_PAGINATION": "The pagination parameters are invalid.",
}


class ApiError(Exception):
    """A rejected request carrying the catalogue identifier and its HTTP status."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."
        )
