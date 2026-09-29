"""Error catalog (PRD section 5 / scaffold 1.6)."""


ERROR_HTTP = {
    # auth
    "ERR_UNAUTHENTICATED": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_ACCOUNT_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # request shape
    "ERR_INVALID_REQUEST": 400,
    # existence
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_ASSET_UNIT_NOT_FOUND": 404,
    "ERR_DISPOSAL_SITE_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_DEPLOYMENT_NOT_FOUND": 404,
    "ERR_SCHEDULE_NOT_FOUND": 404,
    "ERR_VISIT_NOT_FOUND": 404,
    "ERR_MANIFEST_NOT_FOUND": 404,
    "ERR_CHARGE_NOT_FOUND": 404,
    # optimistic concurrency
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_ROUTE_VERSION": 412,
    # state
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_SITE_POSTURE_BLOCKED": 409,
    "ERR_SITE_POSTURE_RESTRICTED": 409,
    "ERR_ROUTE_SUSPENDED": 409,
    "ERR_DISPOSAL_SITE_CLOSED": 409,
    "ERR_PERMIT_REVISION_LIMIT": 409,
    # business constraints
    "ERR_SITE_ACCESS_INFEASIBLE": 422,
    "ERR_ACCESS_WINDOW_VIOLATION": 422,
    "ERR_ROUTE_WINDOW_CONFLICT": 409,
    "ERR_UNIT_DOUBLE_BOOKED": 409,
    "ERR_ROUTE_UNIT_CAPACITY_EXCEEDED": 422,
    "ERR_DISPOSAL_CLASS_NOT_ACCEPTED": 422,
    "ERR_MANIFEST_NO_SERVICED_VISITS": 422,
    "ERR_DISPOSAL_CAP_EXCEEDED": 422,
    "ERR_RECONCILIATION_NO_DEPLOYMENTS": 422,
    "ERR_ACCOUNT_BILLING_HOLD": 402,
    "ERR_DISPUTE_WINDOW_CLOSED": 409,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognised X-User-ID / X-User-Role headers.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not authorized for this endpoint.",
    "ERR_ACCOUNT_SCOPE_VIOLATION": "The acting CustomerContact does not own the target resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The user that assessed this charge may not resolve it.",
    "ERR_INVALID_REQUEST": "The request payload is invalid.",
    "ERR_ACCOUNT_NOT_FOUND": "Rental account not found.",
    "ERR_SITE_NOT_FOUND": "Service site not found.",
    "ERR_PERMIT_NOT_FOUND": "Placement permit not found.",
    "ERR_ASSET_UNIT_NOT_FOUND": "Asset unit not found.",
    "ERR_DISPOSAL_SITE_NOT_FOUND": "Disposal site not found.",
    "ERR_ROUTE_NOT_FOUND": "Route not found.",
    "ERR_CONTRACT_NOT_FOUND": "Rental contract not found.",
    "ERR_DEPLOYMENT_NOT_FOUND": "Unit deployment not found.",
    "ERR_SCHEDULE_NOT_FOUND": "Service schedule not found.",
    "ERR_VISIT_NOT_FOUND": "Service visit not found.",
    "ERR_MANIFEST_NOT_FOUND": "Waste manifest not found.",
    "ERR_CHARGE_NOT_FOUND": "Charge event not found.",
    "ERR_STALE_CONTRACT_VERSION": "expected_contract_version does not match the stored contract version.",
    "ERR_STALE_ROUTE_VERSION": "expected_route_version does not match the stored route version.",
    "ERR_INVALID_STATE_TRANSITION": "The requested transition is not declared from the current state.",
    "ERR_SITE_POSTURE_BLOCKED": "The governing service site posture is BLOCKED.",
    "ERR_SITE_POSTURE_RESTRICTED": "The governing service site posture is RESTRICTED.",
    "ERR_ROUTE_SUSPENDED": "The route is SUSPENDED.",
    "ERR_DISPOSAL_SITE_CLOSED": "The disposal facility is CLOSED.",
    "ERR_PERMIT_REVISION_LIMIT": "The permit revision round ceiling has been reached.",
    "ERR_SITE_ACCESS_INFEASIBLE": "The unit does not physically fit the governing site.",
    "ERR_ACCESS_WINDOW_VIOLATION": "The visit window is not contained by the site gate window.",
    "ERR_ROUTE_WINDOW_CONFLICT": "The visit window collides with another visit on the route and date.",
    "ERR_UNIT_DOUBLE_BOOKED": "The asset unit is already committed over part of this interval.",
    "ERR_ROUTE_UNIT_CAPACITY_EXCEEDED": "The route truck capacity would be exceeded.",
    "ERR_DISPOSAL_CLASS_NOT_ACCEPTED": "The facility does not accept this waste class.",
    "ERR_MANIFEST_NO_SERVICED_VISITS": "No SERVICED visit exists on this route and date.",
    "ERR_DISPOSAL_CAP_EXCEEDED": "The facility daily gallon cap would be exceeded.",
    "ERR_RECONCILIATION_NO_DEPLOYMENTS": "The contract has no deployment that reached the site.",
    "ERR_ACCOUNT_BILLING_HOLD": "The owning account is on billing hold.",
    "ERR_DISPUTE_WINDOW_CLOSED": "The charge dispute window has closed.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
