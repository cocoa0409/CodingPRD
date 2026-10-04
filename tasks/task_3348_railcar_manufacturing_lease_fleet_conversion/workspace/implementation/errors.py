"""Error catalog and the exception type carried through every rejection.

Error identifiers and HTTP statuses are taken verbatim from PRD.md section 5
(Error Code Catalogue); the trigger conditions live in PRD sections 2 and 3 and
are enforced by the route/service layers in the order fixed by PRD section 2.11.
"""


class ApiError(Exception):
    """A rejection carrying the exact error_id / message / http status."""

    def __init__(self, error_id, message, http_status=None):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status if http_status is not None else ERROR_HTTP[error_id]


# --- PRD section 5: Error ID -> HTTP status ---------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SELF_APPROVAL_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_COMPONENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_ALREADY_TERMINAL": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_REGULATORY_LIFE_EXCEEDED": 422,
    "ERR_RETROFIT_DEADLINE_PASSED": 422,
    "ERR_SHOP_SLOT_OVERLAP": 409,
    "ERR_ASSIGNMENT_OVERLAP": 409,
    "ERR_CHANGEOVER_CONFLICT": 409,
    "ERR_COMPONENT_SHORTAGE": 409,
    "ERR_LEAD_TIME_INFEASIBLE": 422,
    "ERR_MATERIAL_ENDORSEMENT_PENDING": 409,
    "ERR_ENDORSEMENT_RETRY_EXHAUSTED": 409,
    "ERR_PREREQUISITE_NOT_MET": 409,
    "ERR_DUPLICATE_ROW": 409,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CREDIT_LIMIT_EXCEEDED": 402,
    "ERR_FLEET_CAP_EXCEEDED": 402,
    "ERR_SETTLEMENT_UNBALANCED": 409,
    "ERR_CAR_NOT_HELD": 409,
    "ERR_LESSEE_MISMATCH": 409,
    "ERR_UNSETTLED_RETURNS": 409,
    "ERR_CAPACITY_EXCEEDED": 409,
}

# Shorthand constructors used across the service layer.

def unauthenticated(msg="X-User-ID and X-User-Role headers are required and must name a declared role."):
    return ApiError("ERR_UNAUTHENTICATED", msg)


def forbidden(msg="The acting role is not permitted for this operation."):
    return ApiError("ERR_FORBIDDEN", msg)


def not_found(what="resource"):
    return ApiError("ERR_NOT_FOUND", "No persisted %s matches the identifier in the path." % what)


def fk_not_found(what="foreign key"):
    return ApiError("ERR_COMPONENT_NOT_FOUND",
                    "The %s named in the request body does not resolve to a persisted row." % what)


def invalid_state(msg="The resource is not in a state from which this action is legal."):
    return ApiError("ERR_INVALID_STATE", msg)


def already_terminal(msg="The resource has reached a terminal state and accepts no further transitions."):
    return ApiError("ERR_ALREADY_TERMINAL", msg)


def stale_version(msg="The supplied expected version does not equal the resource's current version."):
    return ApiError("ERR_STALE_VERSION", msg)


def invalid_request(msg="A required field is missing, an enum member is illegal, or a numeric range fails."):
    return ApiError("ERR_INVALID_REQUEST", msg)


def duplicate_row(msg="A declared uniqueness constraint is violated."):
    return ApiError("ERR_DUPLICATE_ROW", msg)


def prerequisite_not_met(msg="A required upstream aggregate is missing."):
    return ApiError("ERR_PREREQUISITE_NOT_MET", msg)
