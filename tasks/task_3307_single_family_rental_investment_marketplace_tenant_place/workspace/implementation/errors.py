"""Error classes and error ID constants (from SCAFFOLD errors catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def missing_headers(msg="Missing or malformed X-User-ID or X-User-Role header"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400, msg)


def forbidden(msg="Role not permitted for endpoint or ownership check failed"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg="Entity not in a state from which the requested transition is defined"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def segregation(msg="Segregation of duties violation"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 409, msg)


def validation(msg="Shape/type/enum/range constraint violated"):
    return ApiError("ERR_VALIDATION", 422, msg)


def expired(msg="Logical-clock temporal violation"):
    return ApiError("ERR_EXPIRED", 409, msg)


def precondition(msg="Cross-entity precondition failed"):
    return ApiError("ERR_PRECONDITION", 409, msg)


def insufficient_funds(msg="Funds/fee check failed"):
    return ApiError("ERR_INSUFFICIENT_FUNDS", 402, msg)


def stale_listing(msg="expected_listing_version mismatch"):
    return ApiError("ERR_STALE_LISTING_VERSION", 412, msg)


def stale_escrow(msg="expected_escrow_version mismatch"):
    return ApiError("ERR_STALE_ESCROW_VERSION", 412, msg)


def negotiation_exceeded(msg="RESUBMIT attempted when round_number >= MAX_NEGOTIATION_ROUNDS"):
    return ApiError("ERR_NEGOTIATION_ROUND_EXCEEDED", 409, msg)


def not_claimable(msg="Guarantee claim conditions unmet"):
    return ApiError("ERR_GUARANTEE_NOT_CLAIMABLE", 409, msg)


def remote_signing(msg="remote_notarization_ref required for out-of-state signing"):
    return ApiError("ERR_REMOTE_SIGNING_REQUIRED", 409, msg)


def undisclosed_condition(msg="condition_code not present in latest VERIFIED inspection report"):
    return ApiError("ERR_DISPUTE_CONDITION_UNDISCLOSED", 409, msg)


def lease_overlap(msg="Lease period overlaps an existing ACTIVE lease"):
    return ApiError("ERR_LEASE_PERIOD_OVERLAP", 409, msg)


def duplicate_due_month(msg="A payment record for the same due month already exists"):
    return ApiError("ERR_DUPLICATE_DUE_MONTH", 409, msg)
