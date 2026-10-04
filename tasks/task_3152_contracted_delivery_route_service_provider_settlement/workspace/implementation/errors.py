"""Error catalog: the exact error ids and HTTP statuses from SCAFFOLD §1.6."""

ERR_MISSING_AUTH_HEADER = "ERR_MISSING_AUTH_HEADER"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_PROVIDER_NOT_FOUND = "ERR_PROVIDER_NOT_FOUND"
ERR_SERVICE_AREA_NOT_FOUND = "ERR_SERVICE_AREA_NOT_FOUND"
ERR_AGREEMENT_NOT_FOUND = "ERR_AGREEMENT_NOT_FOUND"
ERR_SETTLEMENT_PERIOD_NOT_FOUND = "ERR_SETTLEMENT_PERIOD_NOT_FOUND"
ERR_ASSIGNMENT_NOT_FOUND = "ERR_ASSIGNMENT_NOT_FOUND"
ERR_VEHICLE_NOT_FOUND = "ERR_VEHICLE_NOT_FOUND"
ERR_DRIVER_NOT_FOUND = "ERR_DRIVER_NOT_FOUND"
ERR_CHARGEBACK_CLAIM_NOT_FOUND = "ERR_CHARGEBACK_CLAIM_NOT_FOUND"
ERR_DISPUTE_NOT_FOUND = "ERR_DISPUTE_NOT_FOUND"
ERR_PEAK_DECLARATION_NOT_FOUND = "ERR_PEAK_DECLARATION_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
ERR_AREA_ALREADY_ASSIGNED = "ERR_AREA_ALREADY_ASSIGNED"
ERR_TEMPORAL_OVERLAP = "ERR_TEMPORAL_OVERLAP"
ERR_DRIVER_HOURS_EXCEEDED = "ERR_DRIVER_HOURS_EXCEEDED"
ERR_DRIVER_NOT_QUALIFIED = "ERR_DRIVER_NOT_QUALIFIED"
ERR_INSURANCE_INSUFFICIENT = "ERR_INSURANCE_INSUFFICIENT"
ERR_BRANDING_NONCOMPLIANT = "ERR_BRANDING_NONCOMPLIANT"
ERR_VEHICLE_INELIGIBLE = "ERR_VEHICLE_INELIGIBLE"
ERR_STOP_CAPACITY_EXCEEDED = "ERR_STOP_CAPACITY_EXCEEDED"
ERR_PEAK_CAPACITY_EXCEEDED = "ERR_PEAK_CAPACITY_EXCEEDED"
ERR_DEDUCTION_CAP_EXCEEDED = "ERR_DEDUCTION_CAP_EXCEEDED"
ERR_CHARGEBACK_OUTSTANDING = "ERR_CHARGEBACK_OUTSTANDING"
ERR_DISPUTE_WINDOW_EXPIRED = "ERR_DISPUTE_WINDOW_EXPIRED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_NEGOTIATION_ROUND_LIMIT = "ERR_NEGOTIATION_ROUND_LIMIT"

ERROR_HTTP = {
    ERR_MISSING_AUTH_HEADER: 401,
    ERR_UNAUTHORIZED: 403,
    ERR_PROVIDER_NOT_FOUND: 404,
    ERR_SERVICE_AREA_NOT_FOUND: 404,
    ERR_AGREEMENT_NOT_FOUND: 404,
    ERR_SETTLEMENT_PERIOD_NOT_FOUND: 404,
    ERR_ASSIGNMENT_NOT_FOUND: 404,
    ERR_VEHICLE_NOT_FOUND: 404,
    ERR_DRIVER_NOT_FOUND: 404,
    ERR_CHARGEBACK_CLAIM_NOT_FOUND: 404,
    ERR_DISPUTE_NOT_FOUND: 404,
    ERR_PEAK_DECLARATION_NOT_FOUND: 404,
    ERR_INVALID_REQUEST: 400,
    ERR_INVALID_STATE: 409,
    ERR_ALREADY_TERMINAL: 409,
    ERR_AREA_ALREADY_ASSIGNED: 409,
    ERR_TEMPORAL_OVERLAP: 409,
    ERR_DRIVER_HOURS_EXCEEDED: 409,
    ERR_DRIVER_NOT_QUALIFIED: 422,
    ERR_INSURANCE_INSUFFICIENT: 422,
    ERR_BRANDING_NONCOMPLIANT: 422,
    ERR_VEHICLE_INELIGIBLE: 422,
    ERR_STOP_CAPACITY_EXCEEDED: 422,
    ERR_PEAK_CAPACITY_EXCEEDED: 422,
    ERR_DEDUCTION_CAP_EXCEEDED: 422,
    ERR_CHARGEBACK_OUTSTANDING: 422,
    ERR_DISPUTE_WINDOW_EXPIRED: 422,
    ERR_STALE_VERSION: 412,
    ERR_NEGOTIATION_ROUND_LIMIT: 422,
}

DEFAULT_MESSAGES = {
    ERR_MISSING_AUTH_HEADER: "X-User-ID and X-User-Role headers are required.",
    ERR_UNAUTHORIZED: "The calling role is not authorized for this operation.",
    ERR_PROVIDER_NOT_FOUND: "The service provider id does not resolve.",
    ERR_SERVICE_AREA_NOT_FOUND: "The service area id does not resolve.",
    ERR_AGREEMENT_NOT_FOUND: "The agreement id does not resolve.",
    ERR_SETTLEMENT_PERIOD_NOT_FOUND: "The settlement period id does not resolve.",
    ERR_ASSIGNMENT_NOT_FOUND: "The route assignment id does not resolve.",
    ERR_VEHICLE_NOT_FOUND: "The vehicle id does not resolve.",
    ERR_DRIVER_NOT_FOUND: "The driver id does not resolve.",
    ERR_CHARGEBACK_CLAIM_NOT_FOUND: "The charge-back claim id does not resolve.",
    ERR_DISPUTE_NOT_FOUND: "The dispute id does not resolve.",
    ERR_PEAK_DECLARATION_NOT_FOUND: "The peak-season declaration id does not resolve.",
    ERR_INVALID_REQUEST: "The request is missing a required field or carries an invalid value.",
    ERR_INVALID_STATE: "The requested transition is not legal from the current status.",
    ERR_ALREADY_TERMINAL: "The resource is already in a terminal state.",
    ERR_AREA_ALREADY_ASSIGNED: "Another route assignment on this service area is active or pending transfer.",
    ERR_TEMPORAL_OVERLAP: "The candidate occupancy interval overlaps another assignment on this service area.",
    ERR_DRIVER_HOURS_EXCEEDED: "The candidate duty interval intersects the preceding duty interval guard buffer.",
    ERR_DRIVER_NOT_QUALIFIED: "A non-temporary driver on this roster is not qualified.",
    ERR_INSURANCE_INSUFFICIENT: "The auto liability coverage is below the agreement floor or has expired.",
    ERR_BRANDING_NONCOMPLIANT: "A non-temporary vehicle of the provider fails branding compliance.",
    ERR_VEHICLE_INELIGIBLE: "The vehicle class does not clear the service area eligibility tier.",
    ERR_STOP_CAPACITY_EXCEEDED: "The week's summed stops exceed the service area stop capacity.",
    ERR_PEAK_CAPACITY_EXCEEDED: "No active peak-season declaration covers this asset or its authorized count is exhausted.",
    ERR_DEDUCTION_CAP_EXCEEDED: "The non-chargeback deduction segments exceed the deduction cap.",
    ERR_CHARGEBACK_OUTSTANDING: "The provider carries an outstanding charge-back balance.",
    ERR_DISPUTE_WINDOW_EXPIRED: "The dispute filing window has expired.",
    ERR_STALE_VERSION: "The supplied expected version no longer matches the parent's current version.",
    ERR_NEGOTIATION_ROUND_LIMIT: "The negotiation round budget is exhausted or the renewal window forbids this round.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        self.error_id = error_id
        self.message = message or DEFAULT_MESSAGES.get(error_id, "Request failed.")
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        super().__init__("%s: %s" % (self.error_id, self.message))