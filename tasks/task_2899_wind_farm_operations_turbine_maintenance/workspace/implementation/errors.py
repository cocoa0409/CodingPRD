"""Error catalogue for the Wind Farm Operations & Turbine Maintenance API.

Every identifier and HTTP status here is taken verbatim from PRD section 5 and
the SCAFFOLD `errors` table.
"""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CREW_NOT_ASSIGNED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_FARM_NOT_FOUND": 404,
    "ERR_TURBINE_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_FAULT_EVENT_NOT_FOUND": 404,
    "ERR_PATH_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_STALE_FARM_VERSION": 412,
    "ERR_STALE_TURBINE_VERSION": 412,
    "ERR_WORK_ORDER_INVALID_STATE": 409,
    "ERR_FAULT_EVENT_INVALID_STATE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_TURBINE_DECOMMISSIONED": 409,
    "ERR_WEATHER_WINDOW_NOT_CONFIRMED": 409,
    "ERR_TURBINE_FORCE_STOPPED": 409,
    "ERR_AGREEMENT_IN_SETTLEMENT": 409,
    "ERR_SETTLEMENT_PERIOD_OVERLAP": 409,
    "ERR_WEATHER_WINDOW_OVERLAP": 409,
    "ERR_CREW_WINDOW_CONFLICT": 409,
    "ERR_CRANE_BUFFER_CONFLICT": 409,
    "ERR_CURTAILMENT_STACK_LIMIT": 409,
    "ERR_LIFT_WIND_LIMIT_EXCEEDED": 422,
    "ERR_CREW_WIND_LIMIT_EXCEEDED": 422,
    "ERR_CREW_CERTIFICATION_MISSING": 422,
    "ERR_WORK_ORDER_OUTSIDE_WINDOW": 422,
    "ERR_CREW_FARM_MISMATCH": 422,
    "ERR_CRANE_FARM_MISMATCH": 422,
    "ERR_SPARE_PART_TYPE_MISMATCH": 422,
    "ERR_UPTOWER_NOT_PERMITTED": 422,
    "ERR_RESET_NOT_PERMITTED": 422,
    "ERR_RESET_QUOTA_EXHAUSTED": 422,
    "ERR_CREW_CAPACITY_EXCEEDED": 422,
    "ERR_SPARE_PART_UNAVAILABLE": 422,
    "ERR_MINIMUM_PAYMENT_ABOVE_CAP": 422,
    "ERR_SERVICE_NOT_DUE": 422,
    "ERR_REVISION_LIMIT_EXCEEDED": 422,
    "ERR_NO_TURBINES_IN_SERVICE": 422,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Authentication headers are missing, empty or name an unknown role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids the acting user from performing this action.",
    "ERR_CREW_NOT_ASSIGNED": "The acting crew is not the crew assigned to this work order.",
    "ERR_INVALID_REQUEST": "The request is malformed or carries an invalid field value.",
    "ERR_FARM_NOT_FOUND": "The wind farm does not exist.",
    "ERR_TURBINE_NOT_FOUND": "The turbine does not exist.",
    "ERR_WORK_ORDER_NOT_FOUND": "The work order does not exist.",
    "ERR_FAULT_EVENT_NOT_FOUND": "The fault event does not exist.",
    "ERR_PATH_RESOURCE_NOT_FOUND": "The requested resource does not exist.",
    "ERR_REFERENCE_NOT_FOUND": "A referenced resource does not exist.",
    "ERR_STALE_FARM_VERSION": "The supplied expected_wind_farm_version does not match the farm's current version.",
    "ERR_STALE_TURBINE_VERSION": "The supplied expected_turbine_version does not match the turbine's current version.",
    "ERR_WORK_ORDER_INVALID_STATE": "The work order is not in a state from which this transition is declared.",
    "ERR_FAULT_EVENT_INVALID_STATE": "The fault event is not in a state from which this transition is declared.",
    "ERR_INVALID_STATE": "The resource is not in a state from which this transition is declared.",
    "ERR_TURBINE_DECOMMISSIONED": "The turbine has been decommissioned.",
    "ERR_WEATHER_WINDOW_NOT_CONFIRMED": "The named weather window is not CONFIRMED.",
    "ERR_TURBINE_FORCE_STOPPED": "The turbine is force stopped on the curtailment dimension.",
    "ERR_AGREEMENT_IN_SETTLEMENT": "A service agreement on this farm is in settlement.",
    "ERR_SETTLEMENT_PERIOD_OVERLAP": "The settlement period overlaps an existing settlement for this parcel.",
    "ERR_WEATHER_WINDOW_OVERLAP": "The weather window overlaps an existing window on this farm.",
    "ERR_CREW_WINDOW_CONFLICT": "The crew is already committed over the proposed interval.",
    "ERR_CRANE_BUFFER_CONFLICT": "The buffered crane slot collides with an existing mobilization.",
    "ERR_CURTAILMENT_STACK_LIMIT": "The turbine already holds the maximum number of active curtailment orders.",
    "ERR_LIFT_WIND_LIMIT_EXCEEDED": "The mobilization window does not offer enough workable lift days.",
    "ERR_CREW_WIND_LIMIT_EXCEEDED": "The crew's wind limit is below the window's forecast wind speed.",
    "ERR_CREW_CERTIFICATION_MISSING": "The crew does not hold the required certification.",
    "ERR_WORK_ORDER_OUTSIDE_WINDOW": "The planned interval is not contained inside the weather window.",
    "ERR_CREW_FARM_MISMATCH": "The crew belongs to a different farm than the work order's turbine.",
    "ERR_CRANE_FARM_MISMATCH": "The crane mobilization belongs to a different farm.",
    "ERR_SPARE_PART_TYPE_MISMATCH": "The spare part's component type differs from the replacement's component type.",
    "ERR_UPTOWER_NOT_PERMITTED": "The up-tower branch is not permitted for this replacement.",
    "ERR_RESET_NOT_PERMITTED": "A remote reset is not permitted for this fault event.",
    "ERR_RESET_QUOTA_EXHAUSTED": "The remote reset quota for this fault event is exhausted.",
    "ERR_CREW_CAPACITY_EXCEEDED": "The crew's daily hours capacity would be exceeded.",
    "ERR_SPARE_PART_UNAVAILABLE": "No unit of the named spare part is available to reserve.",
    "ERR_MINIMUM_PAYMENT_ABOVE_CAP": "The minimum payment exceeds the farm's remaining landowner budget headroom.",
    "ERR_SERVICE_NOT_DUE": "The turbine is not yet inside the scheduled-service creation window.",
    "ERR_REVISION_LIMIT_EXCEEDED": "The work order has exhausted its revision rounds.",
    "ERR_NO_TURBINES_IN_SERVICE": "The farm has no turbine in service, so the availability denominator would be zero.",
}


class ApiError(Exception):
    """Carries an error_id from the catalogue plus its HTTP status."""

    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)
