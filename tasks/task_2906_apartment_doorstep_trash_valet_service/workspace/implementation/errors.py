"""Error catalog (PRD s5 / SCAFFOLD s1.6) and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


ERROR_HTTP = {
    # 401
    "ERR_UNAUTHENTICATED": 401,
    # 403
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # 404
    "ERR_PROPERTY_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_RESIDENT_NOT_FOUND": 404,
    "ERR_CONTRACTOR_NOT_FOUND": 404,
    "ERR_SERVICE_NIGHT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_SCAN_NOT_FOUND": 404,
    "ERR_FINE_NOT_FOUND": 404,
    "ERR_INCIDENT_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    # 422
    "ERR_INVALID_REQUEST": 422,
    "ERR_SERVICE_DATE_NOT_SCHEDULED": 422,
    "ERR_INVALID_MAKEUP_DATE": 422,
    "ERR_UNIT_RANGE_OUT_OF_BOUNDS": 422,
    # 409
    "ERR_CROSS_PROPERTY_REFERENCE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_TAG_NOT_FINEABLE": 409,
    "ERR_PROPERTY_SUSPENDED": 409,
    "ERR_CONTRACTOR_NOT_ELIGIBLE": 409,
    "ERR_COMPACTOR_BLOCKED": 409,
    "ERR_CONTRACT_PERIOD_OVERLAP": 409,
    "ERR_CONTRACTOR_WINDOW_CONFLICT": 409,
    "ERR_ESCALATION_WINDOW_NOT_ELAPSED": 409,
    "ERR_UNIT_RANGE_OVERLAP": 409,
    "ERR_UNIT_ALREADY_OCCUPIED": 409,
    "ERR_UNIT_NOT_IN_ROUTE": 409,
    "ERR_DUPLICATE_SCAN": 409,
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": 409,
    "ERR_PERIOD_ALREADY_INVOICED": 409,
    "ERR_PERIOD_NOT_CLOSED": 409,
    "ERR_PASSTHROUGH_DISABLED": 409,
    "ERR_FINE_CAP_EXHAUSTED": 409,
    # 412
    "ERR_STALE_SERVICE_NIGHT_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers must be present, non-blank and name a declared role.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "Segregation of duties forbids this operator from performing this action.",
    "ERR_PROPERTY_NOT_FOUND": "No Property with the given id.",
    "ERR_CONTRACT_NOT_FOUND": "No ServiceContract with the given id.",
    "ERR_RESIDENT_NOT_FOUND": "No Resident with the given id.",
    "ERR_CONTRACTOR_NOT_FOUND": "No ValetContractor with the given id.",
    "ERR_SERVICE_NIGHT_NOT_FOUND": "No ServiceNight with the given id.",
    "ERR_ROUTE_NOT_FOUND": "No RouteAssignment with the given id.",
    "ERR_SCAN_NOT_FOUND": "No ServiceScan with the given id.",
    "ERR_FINE_NOT_FOUND": "No ResidentFine with the given id.",
    "ERR_INCIDENT_NOT_FOUND": "No CompactorIncident with the given id.",
    "ERR_STATEMENT_NOT_FOUND": "No MonthlyStatement with the given id.",
    "ERR_INVALID_REQUEST": "The request body or query string failed shape validation.",
    "ERR_SERVICE_DATE_NOT_SCHEDULED": "service_date is not a scheduled weekday of the contract or lies outside its effective period.",
    "ERR_INVALID_MAKEUP_DATE": "makeup_service_date is absent or invalid for this shift reschedule.",
    "ERR_UNIT_RANGE_OUT_OF_BOUNDS": "A unit number lies outside the property's closed unit range.",
    "ERR_CROSS_PROPERTY_REFERENCE": "The referenced resource belongs to a different property.",
    "ERR_INVALID_STATE": "The requested transition is not declared from the resource's current state.",
    "ERR_ALREADY_TERMINAL": "The addressed resource has already reached a terminal state.",
    "ERR_TAG_NOT_FINEABLE": "The scan's tag_status is not OPEN.",
    "ERR_PROPERTY_SUSPENDED": "The owning property is SUSPENDED or TERMINATED.",
    "ERR_CONTRACTOR_NOT_ELIGIBLE": "The contractor is not CLEARED or is still UNCLASSIFIED.",
    "ERR_COMPACTOR_BLOCKED": "An escalated JAM incident blocks doorstep collection at this property.",
    "ERR_CONTRACT_PERIOD_OVERLAP": "The contract's closed effective interval intersects an existing DRAFT or ACTIVE contract.",
    "ERR_CONTRACTOR_WINDOW_CONFLICT": "The contractor already holds a live route on an intersecting service window.",
    "ERR_ESCALATION_WINDOW_NOT_ELAPSED": "The acknowledgement window has not yet elapsed.",
    "ERR_UNIT_RANGE_OVERLAP": "The requested unit range intersects another live route on this night.",
    "ERR_UNIT_ALREADY_OCCUPIED": "Another ACTIVE resident already occupies this unit_number.",
    "ERR_UNIT_NOT_IN_ROUTE": "The scanned resident's unit_number lies outside the route's range.",
    "ERR_DUPLICATE_SCAN": "A scan already exists for this route assignment and resident.",
    "ERR_DISPUTE_ROUNDS_EXHAUSTED": "The fine's dispute budget is exhausted.",
    "ERR_PERIOD_ALREADY_INVOICED": "An ISSUED statement already covers this billing_period.",
    "ERR_PERIOD_NOT_CLOSED": "A service night of the billing period is not yet terminal.",
    "ERR_PASSTHROUGH_DISABLED": "The resident has fee_passthrough_enabled false and cannot be fined.",
    "ERR_FINE_CAP_EXHAUSTED": "The resident's monthly fine cap has no headroom left.",
    "ERR_STALE_SERVICE_NIGHT_VERSION": "expected_service_night_version does not match the night's current version.",
    "ERR_STALE_CONTRACT_VERSION": "expected_contract_version does not match the contract's current version.",
}
