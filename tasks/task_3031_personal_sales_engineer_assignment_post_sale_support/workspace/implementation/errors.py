"""Error catalogue: identifiers, HTTP statuses, messages, ApiError.

This module is the dependency root: it imports nothing from the rest of the
package so that ``response`` and ``middleware`` can both build on it.
"""


class Err(object):
    # --- auth ---
    UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    UNAUTHORIZED = "ERR_UNAUTHORIZED"
    # --- request shape (evaluated with auth, per PRD §2.11) ---
    MISSING_REQUIRED_FIELD = "ERR_MISSING_REQUIRED_FIELD"
    INVALID_FIELD_VALUE = "ERR_INVALID_FIELD_VALUE"
    # --- existence ---
    CUSTOMER_NOT_FOUND = "ERR_CUSTOMER_NOT_FOUND"
    ENGINEER_NOT_FOUND = "ERR_ENGINEER_NOT_FOUND"
    QUOTE_NOT_FOUND = "ERR_QUOTE_NOT_FOUND"
    INSTRUMENT_UNIT_NOT_FOUND = "ERR_INSTRUMENT_UNIT_NOT_FOUND"
    WARRANTY_PLAN_NOT_FOUND = "ERR_WARRANTY_PLAN_NOT_FOUND"
    BACKORDER_NOT_FOUND = "ERR_BACKORDER_NOT_FOUND"
    GEAR_EXCHANGE_NOT_FOUND = "ERR_GEAR_EXCHANGE_NOT_FOUND"
    REFERENCED_RESOURCE_NOT_FOUND = "ERR_REFERENCED_RESOURCE_NOT_FOUND"
    # --- state ---
    INVALID_STATE = "ERR_INVALID_STATE"
    ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"
    STALE_VERSION = "ERR_STALE_VERSION"
    # --- business rules ---
    BOOK_CAPACITY_EXCEEDED = "ERR_BOOK_CAPACITY_EXCEEDED"
    ASSIGNMENT_COVERAGE_OVERLAP = "ERR_ASSIGNMENT_COVERAGE_OVERLAP"
    TEMPORARY_COVERAGE_UNTIL_REQUIRED = "ERR_TEMPORARY_COVERAGE_UNTIL_REQUIRED"
    COMMISSION_CAP_EXCEEDED = "ERR_COMMISSION_CAP_EXCEEDED"
    CUSTOMER_ASSIGNMENT_REQUIRED = "ERR_CUSTOMER_ASSIGNMENT_REQUIRED"
    DEPENDENCY_CYCLE = "ERR_DEPENDENCY_CYCLE"
    DEPENDENCY_MISSING = "ERR_DEPENDENCY_MISSING"
    INSPECTION_NOT_PASSED = "ERR_INSPECTION_NOT_PASSED"
    SERIAL_ALREADY_REGISTERED = "ERR_SERIAL_ALREADY_REGISTERED"
    REPAIR_ROUNDS_EXHAUSTED = "ERR_REPAIR_ROUNDS_EXHAUSTED"
    SERVICE_CENTER_CAPACITY_FULL = "ERR_SERVICE_CENTER_CAPACITY_FULL"
    SERVICE_CENTER_FAMILY_NOT_ACCEPTED = "ERR_SERVICE_CENTER_FAMILY_NOT_ACCEPTED"
    SERVICE_CENTER_SUSPENDED = "ERR_SERVICE_CENTER_SUSPENDED"
    ENTITLEMENT_REQUIRED = "ERR_ENTITLEMENT_REQUIRED"
    ESCALATION_NOT_PERMITTED = "ERR_ESCALATION_NOT_PERMITTED"
    ESCALATION_DESK_REQUIRED = "ERR_ESCALATION_DESK_REQUIRED"
    SERVICE_CENTER_CAPACITY_FULL_AT_ESCALATION = \
        "ERR_SERVICE_CENTER_CAPACITY_FULL_AT_ESCALATION"
    PREORDER_WINDOW_EXPIRED = "ERR_PREORDER_WINDOW_EXPIRED"
    ZERO_ALLOCATION_REQUEST = "ERR_ZERO_ALLOCATION_REQUEST"
    ALLOCATION_POOL_NEGATIVE = "ERR_ALLOCATION_POOL_NEGATIVE"
    TRIAL_WINDOW_EXPIRED = "ERR_TRIAL_WINDOW_EXPIRED"
    RETURN_REASON_NOT_ELIGIBLE = "ERR_RETURN_REASON_NOT_ELIGIBLE"
    RETAKE_NOT_ELIGIBLE = "ERR_RETAKE_NOT_ELIGIBLE"
    QUOTE_NOT_RESERVED = "ERR_QUOTE_NOT_RESERVED"


HTTP_STATUS = {
    Err.MISSING_REQUIRED_FIELD: 400,
    Err.INVALID_FIELD_VALUE: 400,
    Err.UNAUTHENTICATED: 401,
    Err.UNAUTHORIZED: 403,
    Err.ENTITLEMENT_REQUIRED: 403,
    Err.CUSTOMER_NOT_FOUND: 404,
    Err.ENGINEER_NOT_FOUND: 404,
    Err.QUOTE_NOT_FOUND: 404,
    Err.INSTRUMENT_UNIT_NOT_FOUND: 404,
    Err.WARRANTY_PLAN_NOT_FOUND: 404,
    Err.BACKORDER_NOT_FOUND: 404,
    Err.GEAR_EXCHANGE_NOT_FOUND: 404,
    Err.REFERENCED_RESOURCE_NOT_FOUND: 404,
    Err.INVALID_STATE: 409,
    Err.ALREADY_TERMINAL: 409,
    Err.ASSIGNMENT_COVERAGE_OVERLAP: 409,
    Err.SERIAL_ALREADY_REGISTERED: 409,
    Err.SERVICE_CENTER_SUSPENDED: 409,
    Err.PREORDER_WINDOW_EXPIRED: 409,
    Err.TRIAL_WINDOW_EXPIRED: 409,
    Err.QUOTE_NOT_RESERVED: 409,
    Err.STALE_VERSION: 412,
    Err.BOOK_CAPACITY_EXCEEDED: 422,
    Err.TEMPORARY_COVERAGE_UNTIL_REQUIRED: 422,
    Err.COMMISSION_CAP_EXCEEDED: 422,
    Err.CUSTOMER_ASSIGNMENT_REQUIRED: 422,
    Err.DEPENDENCY_CYCLE: 422,
    Err.DEPENDENCY_MISSING: 422,
    Err.INSPECTION_NOT_PASSED: 422,
    Err.REPAIR_ROUNDS_EXHAUSTED: 422,
    Err.SERVICE_CENTER_CAPACITY_FULL: 422,
    Err.SERVICE_CENTER_FAMILY_NOT_ACCEPTED: 422,
    Err.ESCALATION_NOT_PERMITTED: 422,
    Err.ESCALATION_DESK_REQUIRED: 422,
    Err.SERVICE_CENTER_CAPACITY_FULL_AT_ESCALATION: 422,
    Err.ZERO_ALLOCATION_REQUEST: 422,
    Err.ALLOCATION_POOL_NEGATIVE: 422,
    Err.RETURN_REASON_NOT_ELIGIBLE: 422,
    Err.RETAKE_NOT_ELIGIBLE: 422,
}

MESSAGES = {
    Err.UNAUTHENTICATED: "X-User-ID and X-User-Role headers are required and "
                         "X-User-Role must name a declared role.",
    Err.UNAUTHORIZED: "The acting role is not permitted to perform this operation.",
    Err.MISSING_REQUIRED_FIELD: "A required field is absent from the request body.",
    Err.INVALID_FIELD_VALUE: "A field carries a value outside its declared constraint set.",
    Err.CUSTOMER_NOT_FOUND: "No Customer matches the id path segment.",
    Err.ENGINEER_NOT_FOUND: "No Engineer matches the id path segment.",
    Err.QUOTE_NOT_FOUND: "No Quote matches the id path segment.",
    Err.INSTRUMENT_UNIT_NOT_FOUND: "No InstrumentUnit matches the id path segment.",
    Err.WARRANTY_PLAN_NOT_FOUND: "No WarrantyPlan matches the id path segment.",
    Err.BACKORDER_NOT_FOUND: "No Backorder matches the id path segment.",
    Err.GEAR_EXCHANGE_NOT_FOUND: "No GearExchange matches the id path segment.",
    Err.REFERENCED_RESOURCE_NOT_FOUND: "A resource named in the request body does not exist.",
    Err.INVALID_STATE: "The resource is not in a state from which this transition is declared.",
    Err.ALREADY_TERMINAL: "The resource is already in a terminal state.",
    Err.STALE_VERSION: "The asserted version no longer matches the parent's current version.",
    Err.BOOK_CAPACITY_EXCEEDED: "The engineer's active book size has reached max_book_size.",
    Err.ASSIGNMENT_COVERAGE_OVERLAP: "The requested coverage window overlaps a later "
                                     "assignment interval on this customer's book.",
    Err.TEMPORARY_COVERAGE_UNTIL_REQUIRED: "TEMPORARY_COVERAGE requires effective_until and "
                                           "a permanent reason_code must not carry one.",
    Err.COMMISSION_CAP_EXCEEDED: "commission_share_bps exceeds the engineer's commission_cap_bps.",
    Err.CUSTOMER_ASSIGNMENT_REQUIRED: "The customer has no ACTIVE assignment held by this engineer.",
    Err.DEPENDENCY_CYCLE: "The requires_line_id edges among the quote's lines form a cycle.",
    Err.DEPENDENCY_MISSING: "A dependency edge does not resolve inside the quote, or the "
                            "quote is not bundle_ready.",
    Err.INSPECTION_NOT_PASSED: "The instrument is not in a shippable inspection condition.",
    Err.SERIAL_ALREADY_REGISTERED: "serial_number already backs another InstrumentUnit.",
    Err.REPAIR_ROUNDS_EXHAUSTED: "The warranty plan has no remaining repair rounds.",
    Err.SERVICE_CENTER_CAPACITY_FULL: "The service center is at capacity_slots.",
    Err.SERVICE_CENTER_FAMILY_NOT_ACCEPTED: "The center is not authorized for this product family.",
    Err.SERVICE_CENTER_SUSPENDED: "The service center is SUSPENDED and accepts no routes.",
    Err.ENTITLEMENT_REQUIRED: "The customer's tech_support_entitlement is NONE.",
    Err.ESCALATION_NOT_PERMITTED: "The ticket's required_entitlement is BASIC rather than EXTENDED.",
    Err.ESCALATION_DESK_REQUIRED: "The ticket names no escalation service center.",
    Err.SERVICE_CENTER_CAPACITY_FULL_AT_ESCALATION: "The escalation desk is already at capacity_slots.",
    Err.PREORDER_WINDOW_EXPIRED: "The logical clock is past preorder_open_at + 30 days.",
    Err.ZERO_ALLOCATION_REQUEST: "units_requested of 0 defines an empty candidate set.",
    Err.ALLOCATION_POOL_NEGATIVE: "pool_units must not be negative.",
    Err.TRIAL_WINDOW_EXPIRED: "The logical clock is past trial_end_date.",
    Err.RETURN_REASON_NOT_ELIGIBLE: "Only a TONE_MISMATCH return request may proceed.",
    Err.RETAKE_NOT_ELIGIBLE: "A failed attempt at attempt_index 3 may not be rescheduled.",
    Err.QUOTE_NOT_RESERVED: "The instrument's quote is not RESERVED.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        Exception.__init__(self, error_id)
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = http_status if http_status is not None \
            else HTTP_STATUS.get(error_id, 400)


def missing_field(name):
    return ApiError(Err.MISSING_REQUIRED_FIELD, "Field %s is required." % name)


def invalid_value(message):
    return ApiError(Err.INVALID_FIELD_VALUE, message)


def invalid_state(message=None):
    return ApiError(Err.INVALID_STATE, message)


def already_terminal(message=None):
    return ApiError(Err.ALREADY_TERMINAL, message)


def not_found(error_id, message=None):
    return ApiError(error_id, message)


def referenced(message=None):
    return ApiError(Err.REFERENCED_RESOURCE_NOT_FOUND, message)