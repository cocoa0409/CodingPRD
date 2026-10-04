"""Error class carrying error_id, message, http_status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not allowed for this endpoint or resource."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg="Request body is not well-formed."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def idempotency_conflict(msg="idempotency_key reused with a different payload."):
    return ApiError("ERR_IDEMPOTENCY_CONFLICT", 409, msg)


def stale_version(msg="expected version does not match current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="State-machine from-state mismatch."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def already_terminal(msg="Entity is in a terminal state."):
    return ApiError("ERR_ALREADY_TERMINAL", 409, msg)


def member_posture(msg="Member status does not permit the operation."):
    return ApiError("ERR_MEMBER_POSTURE", 409, msg)


def abuse_lock(msg="deposit_reroute_flag blocks this operation."):
    return ApiError("ERR_ABUSE_LOCK", 422, msg)


def temporal_violation(msg="Clock-dependent rule violated."):
    return ApiError("ERR_TEMPORAL_VIOLATION", 422, msg)


def window_overlap(msg="Window overlaps an existing non-terminal window."):
    return ApiError("ERR_WINDOW_OVERLAP", 409, msg)


def duplicate(msg="Unique constraint violated."):
    return ApiError("ERR_DUPLICATE", 409, msg)


def referential_block(msg="Cross-entity referential block."):
    return ApiError("ERR_REFERENTIAL_BLOCK", 422, msg)


def limit_exceeded(msg="Advance amount exceeds usable cushion, SAVINGS account, or zero limit."):
    return ApiError("ERR_LIMIT_EXCEEDED", 422, msg)


def dispute_amount_exceeds(msg="Dispute amount exceeds the disputed deposit amount."):
    return ApiError("ERR_DISPUTE_AMOUNT_EXCEEDS", 422, msg)


def insufficient_funds(msg="Debit amount exceeds available_optimistic_cents."):
    return ApiError("ERR_INSUFFICIENT_FUNDS", 422, msg)


def not_qualifying(msg="Deposit does not qualify for early posting."):
    return ApiError("ERR_NOT_QUALIFYING", 422, msg)
