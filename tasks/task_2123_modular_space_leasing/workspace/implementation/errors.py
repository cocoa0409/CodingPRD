"""Error catalogue (PRD 5) and the ApiError exception."""

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 422,
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_BUILDING_SPEC_NOT_FOUND": 404,
    "ERR_CONFIG_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_ACCESSORY_PACKAGE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_LOGISTICS_JOB_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_REFURB_ORDER_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_LEASE_ALREADY_ACTIVATED": 409,
    "ERR_LEASE_NOT_ACTIVATED": 409,
    "ERR_JOB_NOT_DISPATCHABLE": 409,
    "ERR_ASSESSMENT_NOT_SUBMITTED": 409,
    "ERR_ASSESSMENT_NOT_FINALIZED": 409,
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_STALE_LEASE_VERSION": 412,
    "ERR_ADA_PACKAGE_NON_COMPLIANT": 422,
    "ERR_PERMIT_NOT_APPROVED": 409,
    "ERR_ANCHORING_STANDARD_MISMATCH": 422,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_ENTITY_LINK_MISMATCH": 409,
    "ERR_CONFIG_NOT_PUBLISHED": 409,
    "ERR_BRANCH_SUSPENDED": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_ACCESSORY_ALREADY_ATTACHED": 409,
    "ERR_LEASE_ALREADY_EXTENDED": 409,
    "ERR_DISPUTE_LIMIT_REACHED": 409,
    "ERR_UNIT_OCCUPANCY_CONFLICT": 409,
    "ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED": 409,
    "ERR_PERMIT_LEAD_TIME_VIOLATION": 422,
    "ERR_EXTENSION_NOT_CONTIGUOUS": 422,
    "ERR_YARD_CAPACITY_EXCEEDED": 409,
    "ERR_CUSTOMER_ON_CREDIT_HOLD": 409,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
}

DEFAULT_MESSAGE = {
    "ERR_UNAUTHENTICATED": "Missing or unrecognised authentication context headers.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_NOT_RESOURCE_OWNER": "The caller does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGE.get(error_id, error_id)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)
