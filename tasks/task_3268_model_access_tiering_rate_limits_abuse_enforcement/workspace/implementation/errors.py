"""Error classes and error ID constants."""


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg: str = "Missing or malformed X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg: str = "Caller role not authorized for the endpoint per RBAC."):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg: str = "Path-template resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_request(msg: str = "Missing required field, ill-typed value, or unknown enum member."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def invalid_state(msg: str = "State machine rejects the transition from the current state."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg: str = "OCC expected_abuse_case_version does not match the case's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def segregation_of_duties(msg: str = "Same user attempting two steps that must be performed by different users."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 422, msg)


def model_unavailable(msg: str = "Usage attempted against SUNSET model, or DEPRECATED model by an unpinned organization without recent usage."):
    return ApiError("ERR_MODEL_UNAVAILABLE", 422, msg)


def org_status_blocked(msg: str = "Organization status blocks the requested operation."):
    return ApiError("ERR_ORG_STATUS_BLOCKED", 422, msg)


def period_overlap(msg: str = "Invoice period overlaps an existing invoice for the same organization."):
    return ApiError("ERR_PERIOD_OVERLAP", 409, msg)


def appeal_already_pending(msg: str = "An appeal is already PENDING for the abuse case."):
    return ApiError("ERR_APPEAL_ALREADY_PENDING", 409, msg)


def duplicate_model_version(msg: str = "(model_slug, version_tag) pair already exists on a non-SUNSET model."):
    return ApiError("ERR_DUPLICATE_MODEL_VERSION", 409, msg)


def agreement_conflict(msg: str = "effective_at >= expires_at, or the organization already has an ACTIVE enterprise agreement."):
    return ApiError("ERR_AGREEMENT_CONFLICT", 422, msg)


def invalid_amount(msg: str = "PaymentEvent amount_cents is zero or violates the kind's sign convention."):
    return ApiError("ERR_INVALID_AMOUNT", 422, msg)


def insufficient_credit(msg: str = "Invoice finalize would drive credit_balance_cents negative."):
    return ApiError("ERR_INSUFFICIENT_CREDIT", 422, msg)


def rate_limited(msg: str = "Request exceeds current window's (rpm, tpm) after throttle and burst adjustments."):
    return ApiError("ERR_RATE_LIMITED", 429, msg)


def appeal_forbidden(msg: str = "Appeal filer's X-User-ID does not equal the accused organization's id."):
    return ApiError("ERR_APPEAL_FORBIDDEN", 403, msg)


def action_not_permitted(msg: str = "Caller is not the assigned analyst, or action_type rank exceeds case severity rank."):
    return ApiError("ERR_ACTION_NOT_PERMITTED", 422, msg)


def temporal_invalid(msg: str = "Logical-clock invariant violated."):
    return ApiError("ERR_TEMPORAL_INVALID", 422, msg)


def queue_full(msg: str = "Queue depth has reached QUEUE_MAX_DEPTH (100)."):
    return ApiError("ERR_QUEUE_FULL", 429, msg)
