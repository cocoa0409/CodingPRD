"""Error types and the normative error_id -> HTTP status mapping (PRD section 5)."""

ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_FACILITY_NOT_FOUND": 404,
    "ERR_OPERATOR_NOT_FOUND": 404,
    "ERR_FLIGHT_NOT_FOUND": 404,
    "ERR_TMI_NOT_FOUND": 404,
    "ERR_CONSTRAINT_EVENT_NOT_FOUND": 404,
    "ERR_FORECAST_NOT_FOUND": 404,
    "ERR_GA_REQUEST_NOT_FOUND": 404,
    "ERR_REROUTE_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FACILITY_IDENT_CONFLICT": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PROGRAM_WINDOW_IN_PAST": 422,
    "ERR_INVALID_RATE": 422,
    "ERR_RATE_EXCEEDS_CAPACITY": 422,
    "ERR_NO_CURRENT_FORECAST": 409,
    "ERR_FACILITY_NOT_OPERATIONAL": 409,
    "ERR_TMI_OVERLAP": 409,
    "ERR_CONSTRAINT_EVENT_OVERLAP": 409,
    "ERR_TMI_NOT_ACTIVE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_TMI_TERMINAL": 409,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_SECTOR_CAPACITY_EXCEEDED": 422,
    "ERR_SUBSTITUTION_SAME_FLIGHT": 422,
    "ERR_FLIGHT_NOT_IN_PROGRAM": 422,
    "ERR_SUBSTITUTION_SHIFT_EXCEEDED": 422,
    "ERR_STALE_FLIGHT_DATA": 422,
    "ERR_OPERATOR_TYPE_INELIGIBLE": 422,
    "ERR_GA_WINDOW_OUTSIDE_PROGRAM": 422,
    "ERR_TMI_TYPE_NOT_GDP": 422,
    "ERR_EXTENSION_LIMIT_EXCEEDED": 422,
    "ERR_FLIGHT_NOT_CANCELLABLE": 409,
    "ERR_FACILITY_TYPE_NOT_AIRPORT": 422,
    "ERR_REROUTE_SECTOR_TYPE": 422,
    "ERR_STALE_VERSION": 412,
}


class ApiError(Exception):
    """Domain error carrying a catalog error_id and its HTTP status."""

    def __init__(self, error_id, message, http_status=None):
        if http_status is None:
            http_status = ERROR_HTTP.get(error_id, 500)
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status
